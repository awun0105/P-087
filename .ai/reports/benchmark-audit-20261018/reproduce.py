"""Read-only audit probes: production functions, synthetic inputs, temporary DB only."""
import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.services.orchestration import benchmark
from src.services.orchestration.evaluation import scorecard as evaluation
from src.services.orchestration.jobs import runner
from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.processing.capability import record
from src.services.orchestration.processing.models import MachineCapability
from src.services.orchestration.value.scorecard import hardware_and_cost, machine_minutes
from tests.test_orchestration.test_value_scorecard import _usage
from tests.test_orchestration.test_pipeline_timing import _registry

now = datetime.now(UTC)
results = {}
u = _usage('preview', seconds=60, at=now-timedelta(minutes=2), config_checksum='job-config', runtime_manifest_checksum='worker-software-runtime')
registry = SimpleNamespace(persistence=SimpleNamespace(database=None))
with patch.object(benchmark, 'load_usages', return_value=[u]):
    legacy = benchmark._tool_timings(registry,u.job_id,'job-config','legacy-full-runtime',now-timedelta(hours=1),None,now)
    matching = benchmark._tool_timings(registry,u.job_id,'job-config','worker-software-runtime',now-timedelta(hours=1),None,now)
results['legacy_runtime_filter'] = {'recorded_usage_count':1,'legacy_job_selected_count':len(legacy),'software_job_selected_count':len(matching)}
assert len(legacy)==0 and len(matching)==1

failed = _usage('preview',seconds=7200,outcome='failed',exit_code=1)
attempt = SimpleNamespace(settings=SimpleNamespace(product_job_gpu_hours_max=1),registry=registry,job=SimpleNamespace(job_id=failed.job_id))
with patch.object(runner,'load_usages',return_value=[failed]):
    cap = runner._gpu_budget_at_start(attempt,'preview',None)
results['failed_hours_budget'] = {'previous_failed_hours':2,'cap_hours':1,'returned_spent_and_cap':cap,'new_run_allowed':cap==(0,1)}
assert cap==(0,1)

with tempfile.TemporaryDirectory(prefix='r2s-benchmark-audit-') as directory:
    root=Path(directory)
    db=RuntimeDatabase(f'sqlite:///{root / "audit.db"}')
    def machine(worker,gpu,at):
        return MachineCapability(worker_id=worker,measured_at=at,gpu_name=gpu,cpu_count=4,ram_total_gb=16,disk_free_gb=20)
    a=machine('worker-A','T4',now-timedelta(seconds=1));b=machine('worker-B','A40',now)
    record(db,a);record(db,b)
    captured=[]
    def capture(*args,**kwargs):
        captured.append(kwargs['machine']);return None
    running_on_a=SimpleNamespace(settings=SimpleNamespace(database_url=f'sqlite:///{root / "audit.db"}',benchmark_gpu_hourly_usd=None,benchmark_label=None),registry=SimpleNamespace(),job=SimpleNamespace(job_id='job-on-A'))
    with patch.object(runner,'build_benchmark',side_effect=capture),patch.object(runner,'publish_benchmark'):
        runner._record_benchmark(running_on_a)
    results['machine_attribution']={'actual_worker_assumption':'worker-A','freshest_other_worker':'worker-B','snapshot_worker':captured[0].worker_id,'snapshot_gpu':captured[0].gpu_name}
    assert captured[0].worker_id=='worker-B'

    reg,jid=_registry(root/'fixture')
    job=reg.get_job(jid)
    timings=[benchmark.StageTiming(stage_id='ST-CAMERA-POSE',state='succeeded',scope='attempt',seconds=None),benchmark.StageTiming(stage_id='ST-VISUAL-RECON',state='succeeded',scope='attempt',seconds=30)]
    with patch.object(evaluation,'job_progress',return_value=SimpleNamespace(attempt=1)),patch.object(evaluation,'current_attempt_stage_timings',return_value=timings):
        metrics=evaluation._system_metrics(reg,job)
    value=next(m for m in metrics if m.key=='system.processing_time')
    results['incomplete_stage_total']={'missing_stage':'ST-CAMERA-POSE','reported_total_seconds':value.value,'display':value.display,'verdict':value.verdict,'meaning':value.meaning}
    assert value.value==30 and value.verdict is None

complete=_usage('preview',seconds=3600)
_,_,price1=hardware_and_cost([complete],0.5)
_,_,price2=hardware_and_cost([complete],1.0)
results['live_rate_reprices_history']={'same_usage_hours':1,'rate_1':0.5,'cost_1':price1.value,'rate_2':1,'cost_2':price2.value}
partial=machine_minutes([_usage('prepare',seconds=60)],'job-score')
results['partial_usage_looks_measured']={'only_tool':'prepare','reported_minutes':partial.value,'provenance':partial.provenance,'note':partial.note}
assert partial.provenance=='measured' and partial.value==1
output=Path('.ai/reports/benchmark-audit-20261018/reproduction-results.json')
output.write_text(json.dumps(results,indent=2,ensure_ascii=False)+'\n')
print(json.dumps(results,indent=2,ensure_ascii=False))

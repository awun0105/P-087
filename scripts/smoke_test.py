"""Application/Foundation sanity smoke test."""

import sys
from pathlib import Path


def run_smoke_test():
    print("--- Smoke Test ---")
    try:
        from src.models.contracts.artifacts import ArtifactRef
        from src.models.contracts.identity import verify_content_checksum
        from src.models.contracts.manifests import InputManifest
        from src.services.orchestration.artifacts import ArtifactResolver

        root = Path(__file__).resolve().parents[1]
        fixtures = root / "fixtures"
        resolver = ArtifactResolver(fixtures / "artifact_store")

        # Parse fixture
        manifest_path = fixtures / "mock_job/input_manifest.json"
        if not manifest_path.exists():
            print(f"[FAIL] Fixture not found: {manifest_path}")
            return False

        print("[PASS] Loading canonical contracts")
        manifest_json = manifest_path.read_text(encoding="utf-8")
        manifest = InputManifest.model_validate_json(manifest_json)
        print("[PASS] Serializing/deserializing fixture")

        # Verify checksum
        verify_content_checksum(manifest, "input_manifest_checksum")
        print("[PASS] Checksum verification")

        # Resolve ArtifactRef
        for f in manifest.files:
            if f.artifact_uri:
                ref = ArtifactRef(
                    schema_version="1.0",
                    artifact_type="InputFile",
                    artifact_uri=f.artifact_uri,
                    artifact_checksum=f.checksum,
                    data_class=f.data_class,
                    producer_stage="ST-INPUT",
                )
                resolver.require(ref)
        print("[PASS] Artifact resolution")

        print("[PASS] Synthetic handoff simulation successful.")
        return True
    except Exception as e:
        print(f"[FAIL] Smoke test encountered an error: {e}")
        return False


def main():
    if run_smoke_test():
        print("\nSmoke test finished successfully. Foundation logic is sane.")
        sys.exit(0)
    else:
        print("\nSmoke test failed. Foundation logic issues detected.")
        sys.exit(1)


if __name__ == "__main__":
    main()

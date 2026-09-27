/** Full PLY-storage similarity bằng upstream streaming TRS/quaternion/SH writer. */
import { readFileSync, writeFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { readFileSystem, outputFileSystem } from './splat_io.mjs';

const target = statSync(process.argv[2]).isDirectory()
    ? join(process.argv[2], 'dist', 'index.mjs') : process.argv[2];
const api = await import(pathToFileURL(target).href);
if (api.version !== '3.6.6' || api.revision !== 'afbc281') throw new Error('Unqualified splat runtime');
const transform = JSON.parse(readFileSync('metric-transform.json', 'utf8'));
const values = [transform.scale_m_per_sfm_unit, ...transform.rotation_xyzw, ...transform.translation_m];
if (!values.every(Number.isFinite) || transform.scale_m_per_sfm_unit <= 0 ||
    transform.rotation_xyzw.length !== 4 || transform.translation_m.length !== 3 ||
    Math.abs(Math.hypot(...transform.rotation_xyzw) - 1) > 1e-9) throw new Error('Invalid similarity');

const inputFs = readFileSystem(api);
async function openChecked(filename) {
    const options = { filename, inputFormat: 'ply', fileSystem: inputFs };
    const info = await api.readFileInfo(options);
    if (!info.gaussian || info.numGaussians < 1 || info.numLods !== 1) throw new Error('Invalid Gaussian PLY');
    const sources = await api.readFile(options);
    try {
        if (sources.length !== 1) throw new Error('Expected one Gaussian source');
        const stats = await api.computeStats(sources[0]);
        const lod = stats.lods[0];
        if ([...lod.data.nanCount, ...lod.data.infCount].some(n => n !== 0)) throw new Error('Nonfinite Gaussian data');
        const checked = await api.processSource(sources[0], [{ kind: 'filterNaN' }], api.createChunkDataPool());
        if (checked.meta.numGaussians !== info.numGaussians) throw new Error('Invalid Gaussian parameters');
        return { source: sources[0], info };
    } catch (error) {
        for (const source of sources) await source.close();
        throw error;
    }
}

const { source, info } = await openChecked('source.ply');
try {
    if (!source.meta.transform.equals(api.Transform.PLY)) throw new Error('Unexpected PLY coordinate convention');
    const metric = new api.Transform();
    metric.translation.set(...transform.translation_m);
    metric.rotation.set(...transform.rotation_xyzw);
    metric.scale = transform.scale_m_per_sfm_unit;
    // Public ChunkSource wrapper, không mutate readonly upstream metadata.
    // Writer delta = PLY^-1 * (PLY * M) = M: desired transform trên raw PLY xyz.
    const mapped = {
        meta: { ...source.meta, transform: source.meta.transform.clone().mul(metric) },
        read: request => source.read(request), close: () => source.close()
    };
    await api.writeSource({ filename: 'input.ply', outputFormat: 'ply', source: mapped,
        pool: api.createChunkDataPool(), options: {} }, outputFileSystem);
} finally {
    await source.close();
}
const output = await openChecked('input.ply');
try {
    if (output.info.numGaussians !== info.numGaussians || output.info.shBands !== info.shBands) {
        throw new Error('Similarity changed Gaussian inventory');
    }
    writeFileSync('metric-transform-receipt.json', JSON.stringify({
        version: api.version, revision: api.revision, transform,
        num_gaussians: info.numGaussians, sh_bands: info.shBands,
        storage_mapping: 'PLY_inverse_times_PLY_times_metric'
    }), { flag: 'wx' });
} finally {
    await output.source.close();
}

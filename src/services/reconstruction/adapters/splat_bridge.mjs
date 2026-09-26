/** REC-04: thin Node I/O bridge, reuse reader/stats/SOG codec MIT upstream. */
import { openSync, closeSync, fstatSync, readSync, writeSync, writeFileSync, mkdirSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

const api = await import(pathToFileURL(process.argv[2]).href);
if (api.version !== '3.6.6') throw new Error('Unsupported splat-transform version');

// Chỉ adapt Node range I/O vào public filesystem interface của upstream.
class FileStream extends api.ReadStream {
    constructor(fd, start, end) {
        super(end - start);
        this.fd = fd;
        this.position = start;
        this.end = end;
    }
    async pull(target) {
        const size = Math.min(target.length, this.end - this.position);
        if (size <= 0) return 0;
        const count = readSync(this.fd, target, 0, size, this.position);
        this.position += count;
        this.bytesRead += count;
        return count;
    }
}

const inputFs = {
    async createSource(filename) {
        const fd = openSync(filename, 'r');
        const size = fstatSync(fd).size;
        let closed = false;
        return {
            size, seekable: true,
            read: (start = 0, end = size) => new FileStream(fd, start, end),
            close() { if (!closed) { closeSync(fd); closed = true; } }
        };
    }
};
const outputFs = {
    async mkdir(path) { mkdirSync(path, { recursive: true }); },
    createWriter(filename) {
        const fd = openSync(filename, 'wx');
        let closed = false;
        return {
            bytesWritten: 0,
            write(data) {
                let offset = 0;
                while (offset < data.length) offset += writeSync(fd, data, offset, data.length - offset);
                this.bytesWritten += data.length;
            },
            close() { if (!closed) { closeSync(fd); closed = true; } },
            abort() { this.close(); }
        };
    }
};

async function inspect(filename, inputFormat) {
    const options = { filename, inputFormat, fileSystem: inputFs };
    const info = await api.readFileInfo(options);
    if (!info.gaussian || info.numGaussians < 1 || info.numLods !== 1) {
        throw new Error('Expected a nonempty, single-LOD Gaussian artifact');
    }
    const sources = await api.readFile(options);
    if (sources.length !== 1) throw new Error('Expected one splat source');
    const source = sources[0];
    try {
        const stats = await api.computeStats(source);
        const lod = stats.lods[0];
        const nonfinite = [...lod.data.nanCount, ...lod.data.infCount].reduce((a, b) => a + b, 0);
        if (nonfinite || !Number.isFinite(lod.fillRatio)) throw new Error('Nonfinite Gaussian data');
        // Upstream filter cũng phát hiện quaternion zero; chỉ so count, không sửa master.
        const checked = await api.processSource(source, [{ kind: 'filterNaN' }], api.createChunkDataPool());
        if (checked.meta.numGaussians !== source.meta.numGaussians) throw new Error('Invalid Gaussian parameters');
        return { info, stats };
    } finally {
        source.close();
    }
}

const master = 'output/visual.ply';
const delivery = 'output/scene.sog';
const { info, stats } = await inspect(master, 'ply');
const sources = await api.readFile({ filename: master, inputFormat: 'ply', fileSystem: inputFs });
try {
    // Reader/writer cùng PLY storage convention: không xoay Z thêm lần nữa.
    // SOG writer tự Morton-sort và CPU SH compression khi không truyền GPU creator.
    await api.writeSource({
        filename: delivery, outputFormat: 'sog-bundle', source: sources[0],
        pool: api.createChunkDataPool(), options: { iterations: Number(process.argv[3]) }
    }, outputFs);
} finally {
    sources[0].close();
}
const decoded = await inspect(delivery, 'sog');
if (decoded.info.numGaussians !== info.numGaussians || decoded.info.shBands !== info.shBands) {
    throw new Error('SOG roundtrip changed Gaussian inventory');
}
writeFileSync('output/inspection.json', JSON.stringify({
    version: api.version, revision: api.revision, gaussian: true,
    num_gaussians: info.numGaussians, sh_bands: info.shBands,
    fill_ratio: stats.lods[0].fillRatio, nonfinite_count: 0,
    ply_to_sog: 'identity_in_ply_storage_space', info, stats
}, null, 2));

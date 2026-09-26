/** REC-05: upstream Gaussian validation; không tự viết parser PLY. */
import { openSync, closeSync, fstatSync, readSync, writeFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

const api = await import(pathToFileURL(process.argv[2]).href);
if (api.version !== '3.6.6' || api.revision !== 'afbc281') throw new Error('Unqualified splat runtime');

class FileStream extends api.ReadStream {
    constructor(fd, start, end) {
        super(end - start);
        Object.assign(this, { fd, position: start, end });
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
const fileSystem = {
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
const options = { filename: 'input.ply', inputFormat: 'ply', fileSystem };
const info = await api.readFileInfo(options);
if (!info.gaussian || info.numGaussians < 1 || info.numLods !== 1) throw new Error('Invalid Gaussian PLY');
const sources = await api.readFile(options);
try {
    if (sources.length !== 1) throw new Error('Expected one Gaussian source');
    const source = sources[0];
    const stats = await api.computeStats(source);
    const lod = stats.lods[0];
    const bad = [...lod.data.nanCount, ...lod.data.infCount].some(value => value !== 0);
    if (bad || !Number.isFinite(lod.fillRatio)) throw new Error('Nonfinite Gaussian data');
    const checked = await api.processSource(source, [{ kind: 'filterNaN' }], api.createChunkDataPool());
    if (checked.meta.numGaussians !== info.numGaussians) throw new Error('Invalid Gaussian parameters');
    writeFileSync('inspection.json', JSON.stringify({ version: api.version, revision: api.revision, info, stats }));
} finally {
    for (const source of sources) source.close();
}

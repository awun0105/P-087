/** Node range IO adapter vào public SplatTransform API; không vendor codec. */
import { openSync, closeSync, fstatSync, readSync, writeSync, mkdirSync } from 'node:fs';

export function readFileSystem(api) {
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
    return {
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
}

export const outputFileSystem = {
    async mkdir(path) { mkdirSync(path, { recursive: true }); },
    createWriter(filename) {
        const fd = openSync(filename, 'wx');
        let closed = false;
        return {
            bytesWritten: 0,
            write(data) {
                let offset = 0;
                while (offset < data.length) {
                    const count = writeSync(fd, data, offset, data.length - offset);
                    if (!count) throw new Error('Incomplete output write');
                    offset += count;
                }
                this.bytesWritten += data.length;
            },
            close() { if (!closed) { closeSync(fd); closed = true; } },
            abort() { this.close(); }
        };
    }
};

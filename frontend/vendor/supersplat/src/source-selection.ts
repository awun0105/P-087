/** Export selection through the upload permutation and live instance indirection. */
export interface SourceSelectionLayer {
    resource: { numRows: number; sourceFileRows: Uint32Array | null; membershipSourceChecksum: string | null };
    instances: { count: number; sourceRow: Uint32Array; flags: Uint8Array };
}

export function selectedSourceRows(layers: SourceSelectionLayer[], checksum: string, rowCount: number): number[] {
    if (layers.length !== 1) throw new Error('Selection requires exactly one immutable source layer');
    const { resource, instances } = layers[0];
    if (resource.membershipSourceChecksum !== checksum || resource.numRows !== rowCount) {
        throw new Error('Selection source checksum or row count mismatch');
    }
    const selected = new Set<number>();
    for (let i = 0; i < instances.count; i++) {
        if ((instances.flags[i] & 1) === 0) continue;
        const row = instances.sourceRow[i];
        const source = resource.sourceFileRows ? resource.sourceFileRows[row] : row;
        if (!Number.isInteger(source) || source < 0 || source >= rowCount) throw new Error('Invalid source row mapping');
        selected.add(source);
        if (selected.size > 250000) throw new Error('Select at most 250000 Gaussians per correction');
    }
    return [...selected].sort((a, b) => a - b);
}

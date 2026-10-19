import { SelectOp } from './edit-ops';
import { Events } from './events';
import { selectedSourceRows } from './source-selection';
import type { Splat } from './splat';

const IS_SCENE_DIRTY = 'supersplat:is-scene-dirty';
const NAVIGATE_HOME = 'supersplat:navigate-home';

interface IsSceneDirtyQuery {
    type: typeof IS_SCENE_DIRTY;
}

interface IsSceneDirtyResponse {
    type: typeof IS_SCENE_DIRTY;
    result: boolean;
}

const isSceneDirtyQuery = (data: any): data is IsSceneDirtyQuery => {
    return (
        data &&
        typeof data === 'object' &&
        data.type === IS_SCENE_DIRTY
    );
};

const registerIframeApi = (events: Events) => {
    window.addEventListener('message', (event: MessageEvent) => {
        const source = event.source as Window | null;
        if (!source) {
            return;
        }

        if (event.origin === window.location.origin && event.source === window.parent && event.data?.type === 'supersplat:source-selection') {
            const { requestId, checksum, rowCount } = event.data;
            try {
                const rows = selectedSourceRows(events.invoke('scene.allSplats') as Splat[], checksum, rowCount);
                source.postMessage({ type: 'supersplat:source-selection', requestId, checksum, rows }, event.origin);
            } catch (cause) {
                source.postMessage({ type: 'supersplat:source-selection', requestId, error: String(cause) }, event.origin);
            }
        }
        if (event.origin === window.location.origin && event.source === window.parent && event.data?.type === 'supersplat:source-highlight') {
            const layers = events.invoke('scene.allSplats') as Splat[];
            const { checksum, rowCount, rows } = event.data;
            try {
                selectedSourceRows(layers, checksum, rowCount);
                if (!Array.isArray(rows) || rows.length > 250000 || rows.some(row => !Number.isInteger(row) || row < 0 || row >= rowCount)) return;
                const wanted = new Set<number>(rows);
                const splat = layers[0];
                const { resource, instances } = splat;
                const mask = new Uint8Array(instances.count);
                for (let i = 0; i < instances.count; i++) {
                    const row = instances.sourceRow[i];
                    if (wanted.has(resource.sourceFileRows ? resource.sourceFileRows[row] : row)) mask[i] = 255;
                }
                events.fire('edit.add', new SelectOp(splat, 'set', mask));
            } catch (cause) {
                source.postMessage({ type: 'supersplat:source-selection', error: String(cause) }, event.origin);
            }
        }
        if (isSceneDirtyQuery(event.data)) {
            const response: IsSceneDirtyResponse = {
                type: IS_SCENE_DIRTY,
                result: events.invoke('scene.dirty') as boolean
            };
            source.postMessage(response, event.origin);
        }
    });
};

interface NavigateHomeRequest {
    type: typeof NAVIGATE_HOME;
}

const isEmbedded = () => window.parent !== window;

// The embedding page's origin: the referrer when the browser sends one, else
// our own origin (superspl.at serves the editor from the same host). Never '*'.
const hostOrigin = () => {
    try {
        return document.referrer ? new URL(document.referrer).origin : window.location.origin;
    } catch {
        return window.location.origin;
    }
};

// The menubar logo. Embedded (superspl.at/editor), the host decides how to
// leave — it owns navigation, the unsaved-changes guard and any transition.
// Standalone, go to the SuperSplat site directly.
const requestNavigateHome = () => {
    if (isEmbedded()) {
        const request: NavigateHomeRequest = { type: NAVIGATE_HOME };
        window.parent.postMessage(request, hostOrigin());
        return;
    }
    window.location.assign('https://superspl.at/');
};

export { registerIframeApi, requestNavigateHome };

"""Download the pinned official COLMAP vocabulary, resuming interrupted transfers."""

import argparse
import fcntl
import math
import re
import sys
from http.client import HTTPException
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src/services/reconstruction/adapters"))

import vocab_tree as asset  # noqa: E402 - standalone stdlib CLI, no application dependency initialization


def download_vocab_tree(output: Path, timeout: float = 30) -> Path:
    """Only publish complete, checksum-verified bytes; keep a partial transfer for the next invocation."""
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Timeout must be finite and positive")
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.with_suffix(output.suffix + ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if asset.verify_vocab_tree(output):
            return output
        partial = output.with_suffix(output.suffix + ".part")
        if asset.verify_vocab_tree(partial):
            partial.replace(output)
            return output
        offset = partial.stat().st_size if partial.exists() else 0
        if offset >= asset.VOCAB_TREE_SIZE:
            partial.unlink()
            offset = 0
        request = Request(asset.VOCAB_TREE_URL, headers={"Range": f"bytes={offset}-"} if offset else {})
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - pinned HTTPS source
            if response.status == 206:
                span = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("Content-Range", ""))
                if span is None or int(span[1]) != offset or int(span[3]) != asset.VOCAB_TREE_SIZE:
                    raise ValueError("Invalid resume response; refusing to append unrelated bytes")
                mode = "ab"
            elif response.status == 200:
                mode, offset = "wb", 0  # Server ignored Range: restart rather than append a second copy.
            else:
                raise ValueError(f"Unexpected HTTP status {response.status}")
            with partial.open(mode) as handle:
                while chunk := response.read(1 << 16):
                    offset += len(chunk)
                    if offset > asset.VOCAB_TREE_SIZE:
                        raise ValueError("Vocabulary response exceeds the pinned size")
                    handle.write(chunk)
        if offset != asset.VOCAB_TREE_SIZE:
            raise OSError("Download interrupted; rerun to resume")
        if not asset.verify_vocab_tree(partial):
            partial.unlink()
            raise ValueError("Vocabulary checksum mismatch; no asset was published")
        partial.replace(output)
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=asset.DEFAULT_VOCAB_TREE_PATH)
    parser.add_argument("--timeout", type=float, default=30, help="Socket timeout in seconds")
    parser.add_argument("--check-only", action="store_true", help="Verify without network or file writes")
    args = parser.parse_args(argv)
    try:
        if args.check_only:
            if not asset.verify_vocab_tree(args.output):
                raise ValueError("Vocabulary missing, incomplete or checksum mismatch")
            path = args.output
        else:
            path = download_vocab_tree(args.output, args.timeout)
        print(f"COLMAP vocabulary verified: {path} (sha256:{asset.VOCAB_TREE_SHA256})")
        return 0
    except (OSError, URLError, HTTPException, ValueError) as error:
        print(f"COLMAP vocabulary: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

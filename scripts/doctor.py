"""Environment and preflight diagnostics."""

import subprocess
import sys


def check_python_version() -> bool:
    print("--- Python Version Check ---")
    version = sys.version_info
    version_str = f"{version.major}.{version.minor}.{version.micro}"

    if version.major == 3 and version.minor == 12:
        if version.micro == 14:
            print(f"[PASS] Python {version_str} (Reference runtime)")
            return True
        else:
            print(f"[PASS][WARNING] Python {version_str} is supported but differs from Foundation reference (3.12.14)")
            return True
    else:
        print(f"[FAIL] Unsupported Python version: {version_str}. Expected: >=3.12, <3.13")
        return False


def check_uv_integrity() -> bool:
    print("--- Dependency Integrity Check (uv) ---")
    try:
        # Check uv version
        uv_version = subprocess.run(["uv", "--version"], capture_output=True, text=True, check=True).stdout.strip()
        print(f"[INFO] Using {uv_version}")

        # Check integrity
        result = subprocess.run(["uv", "pip", "check"], capture_output=True, text=True)
        if result.returncode == 0:
            print("[PASS] uv pip check passed.")
            return True
        else:
            print(f"[FAIL] uv pip check failed:\n{result.stdout}")
            return False
    except Exception as e:
        print(f"[FAIL] Could not run uv pip check: {e}")
        return False


def check_critical_imports() -> bool:
    print("--- Critical Imports Check ---")
    modules = ["fastapi", "pydantic", "src.models.contracts"]
    all_passed = True
    for mod in modules:
        try:
            __import__(mod)
            print(f"[PASS] Imported {mod}")
        except ImportError as e:
            print(f"[FAIL] Could not import {mod}: {e}")
            all_passed = False
    return all_passed


def check_lock_fingerprint() -> bool:
    print("--- Environment Fingerprint Check ---")
    try:
        from src.services.orchestration.environment import get_core_environment_fingerprint

        fp = get_core_environment_fingerprint()
        print(f"[INFO] Python: {fp.python_version.split()[0]}")
        print(f"[INFO] Platform: {fp.platform_system} {fp.platform_release} {fp.platform_machine}")
        if fp.core_lock_checksum:
            print(f"[INFO] Lock Checksum: {fp.core_lock_checksum}")
            return True
        else:
            print("[WARNING] requirements.lock.txt not found. Cannot compute fingerprint.")
            return True
    except Exception as e:
        print(f"[FAIL] Could not generate fingerprint: {e}")
        return False


def main():
    print("Running Doctor...")
    success = True
    success &= check_python_version()
    success &= check_critical_imports()
    success &= check_uv_integrity()
    success &= check_lock_fingerprint()

    if success:
        print("\nDoctor finished successfully. Environment is valid.")
        sys.exit(0)
    else:
        print("\nDoctor found issues. Environment is invalid.")
        sys.exit(1)


if __name__ == "__main__":
    main()

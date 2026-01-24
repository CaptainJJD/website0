import os
import re
import uuid
import subprocess
from pathlib import Path

# ---- Settings ----
THRESHOLD_MB = 7.0          # only process if file is bigger than this
TARGET_LOW_MB = 5.0         # try not to go below this
TARGET_HIGH_MB = 6.0        # try not to exceed this
RESIZE_MAX_EDGE = 3600      # if we resize, this is the ONLY cap used
PANORAMA_SKIP_OVER = 8000   # skip if width OR height exceeds this

# JPEG quality (ffmpeg: lower q = better quality, larger files)
# q=2 is "98%-ish", q=1 is even higher quality (can help avoid going too small),
# higher numbers reduce size if we must.
Q_CANDIDATES = [2, 1, 3, 4, 5, 6]

IMAGE_EXTS = {".jpg", ".jpeg"}

def run_capture(cmd):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return p.returncode, p.stdout, p.stderr

def get_dims_via_ffmpeg(ffmpeg_path: Path, img_path: Path):
    """Extract WxH by parsing ffmpeg stderr (no ffprobe needed)."""
    null_out = "NUL" if os.name == "nt" else "/dev/null"
    cmd = [str(ffmpeg_path), "-hide_banner", "-i", str(img_path), "-f", "null", null_out]
    _, out, err = run_capture(cmd)

    text = (err or "") + "\n" + (out or "")
    video_lines = [ln for ln in text.splitlines() if "Video:" in ln]
    search_space = "\n".join(video_lines) if video_lines else text

    matches = re.findall(r"(\d{2,5})x(\d{2,5})", search_space)
    if not matches:
        return None

    for w_str, h_str in matches:
        w, h = int(w_str), int(h_str)
        if 16 <= w <= 50000 and 16 <= h <= 50000:
            return w, h
    return None

def scale_filter_for_edge(w: int, h: int, edge: int) -> str:
    # Keep aspect ratio; set long edge to "edge"; use Lanczos
    if w >= h:
        return f"scale={edge}:-2:flags=lanczos"
    return f"scale=-2:{edge}:flags=lanczos"

def encode_candidate(ffmpeg_path: Path, src: Path, qv: int, do_resize: bool, w: int, h: int):
    """
    Encode to a temp file. If do_resize True and current max edge > RESIZE_MAX_EDGE, resize to that cap.
    Returns (tmp_path, bytes, resized_flag).
    """
    tmp = src.with_name(f"{src.stem}.__tmp_{uuid.uuid4().hex}{src.suffix}")

    cmd = [
        str(ffmpeg_path),
        "-y",
        "-hide_banner",
        "-loglevel", "error",
        "-i", str(src),
    ]

    resized = False
    if do_resize and max(w, h) > RESIZE_MAX_EDGE:
        cmd += ["-vf", scale_filter_for_edge(w, h, RESIZE_MAX_EDGE)]
        resized = True

    cmd += [
        "-frames:v", "1",
        "-q:v", str(qv),
        "-map_metadata", "0",
        str(tmp),
    ]

    code, out, err = run_capture(cmd)
    if code != 0 or not tmp.exists() or tmp.stat().st_size == 0:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise RuntimeError(err.strip() or out.strip() or "ffmpeg failed")

    return tmp, tmp.stat().st_size, resized

def score_size(sz_bytes: int, low: int, high: int) -> float:
    """
    Prefer landing in [low, high]. Penalize going below low more than being above high.
    """
    mid = (low + high) / 2
    s = abs(sz_bytes - mid)
    if sz_bytes < low:
        s += (low - sz_bytes) * 3.0  # heavy penalty for "too small"
    if sz_bytes > high:
        s += (sz_bytes - high) * 1.5
    return s

def main():
    here = Path(__file__).resolve().parent
    ffmpeg_path = here / "ffmpeg.exe"
    if not ffmpeg_path.exists():
        raise SystemExit(f"ERROR: ffmpeg.exe not found next to the script:\n  {ffmpeg_path}")

    threshold_bytes = int(THRESHOLD_MB * 1024 * 1024)
    low_bytes = int(TARGET_LOW_MB * 1024 * 1024)
    high_bytes = int(TARGET_HIGH_MB * 1024 * 1024)

    imgs = [p for p in here.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS]

    if not imgs:
        print("No JPG/JPEG files found in this folder.")
        return

    ok = skip_under = skip_pano = fail = 0
    print(f"Found {len(imgs)} JPG/JPEG files.")
    print(f"Rule: if > {THRESHOLD_MB} MB -> aim for {TARGET_LOW_MB}-{TARGET_HIGH_MB} MB.")
    print(f"If resize needed: cap long edge to {RESIZE_MAX_EDGE}px (and never below that).\n")

    for src in imgs:
        tmps = []
        try:
            orig_size = src.stat().st_size
            if orig_size <= threshold_bytes:
                print(f"SKIP (<= {THRESHOLD_MB}MB): {src.name}  ({orig_size/1024/1024:.2f} MB)")
                skip_under += 1
                continue

            dims = get_dims_via_ffmpeg(ffmpeg_path, src)
            if not dims:
                print(f"SKIP (can't read dims): {src.name}")
                continue

            w, h = dims
            if w > PANORAMA_SKIP_OVER or h > PANORAMA_SKIP_OVER:
                print(f"SKIP panorama (>8k): {src.name}  ({w}x{h})  ({orig_size/1024/1024:.2f} MB)")
                skip_pano += 1
                continue

            attempts = []

            # 1) Try no-resize first (preserves dimensions)
            for qv in Q_CANDIDATES:
                tmp, sz, resized = encode_candidate(ffmpeg_path, src, qv, do_resize=False, w=w, h=h)
                tmps.append(tmp)
                attempts.append((tmp, sz, qv, resized))

                # If we hit the target range with high quality, good enough
                if low_bytes <= sz <= high_bytes and qv in (2, 1):
                    break

            # 2) If still too big, try a single resize cap to 3600 (only if image is larger than that)
            if all(a[1] > high_bytes for a in attempts) and max(w, h) > RESIZE_MAX_EDGE:
                for qv in Q_CANDIDATES:
                    tmp, sz, resized = encode_candidate(ffmpeg_path, src, qv, do_resize=True, w=w, h=h)
                    tmps.append(tmp)
                    attempts.append((tmp, sz, qv, resized))

                    if low_bytes <= sz <= high_bytes and qv in (2, 1):
                        break

            # Pick best attempt (strongly avoids going below 5MB)
            best = min(attempts, key=lambda a: score_size(a[1], low_bytes, high_bytes))
            best_tmp, best_sz, best_qv, best_resized = best

            # If best isn't smaller than original, skip
            if best_sz >= orig_size:
                print(f"SKIP (no improvement): {src.name}  ({orig_size/1024/1024:.2f} MB)")
                for t in tmps:
                    t.unlink(missing_ok=True)
                continue

            # Replace original
            os.replace(best_tmp, src)

            # Cleanup remaining temps
            for t in tmps:
                if t.exists():
                    t.unlink(missing_ok=True)

            action = "RESIZE->3600" if best_resized else "NO-RESIZE"
            print(f"OK  {src.name}  {action}  q={best_qv}  {orig_size/1024/1024:.2f} -> {best_sz/1024/1024:.2f} MB")
            ok += 1

        except Exception as e:
            print(f"FAIL {src.name}: {e}")
            fail += 1
            for t in tmps:
                t.unlink(missing_ok=True)

    print(f"\nDone ✅  OK={ok}  SKIP_under={skip_under}  SKIP_pano={skip_pano}  FAIL={fail}")

if __name__ == "__main__":
    main()

import os
import re
import uuid
import subprocess
from pathlib import Path

MAX_EDGE = 3600      # target largest dimension
SKIP_OVER = 8000     # skip if width OR height exceeds this

def run_capture(cmd):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return p.returncode, p.stdout, p.stderr

def get_dims_via_ffmpeg(ffmpeg_path: Path, img_path: Path):
    """
    Parse ffmpeg stderr to extract WxH without needing ffprobe.exe.
    """
    null_out = "NUL" if os.name == "nt" else "/dev/null"
    cmd = [str(ffmpeg_path), "-hide_banner", "-i", str(img_path), "-f", "null", null_out]
    code, out, err = run_capture(cmd)

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

def build_scale_filter(w: int, h: int, max_edge: int) -> str:
    # Keep aspect ratio, downscale so the long edge becomes max_edge
    # -2 preserves ratio (and keeps even sizes where relevant)
    if w >= h:
        return f"scale={max_edge}:-2"
    return f"scale=-2:{max_edge}"

def main():
    here = Path(__file__).resolve().parent
    ffmpeg_path = here / "ffmpeg.exe"

    if not ffmpeg_path.exists():
        raise SystemExit(f"ERROR: ffmpeg.exe not found next to the script:\n  {ffmpeg_path}")

    # Only JPG/JPEG in this folder
    imgs = [p for p in here.iterdir()
            if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg"}]

    if not imgs:
        print("No JPG/JPEG files found in this folder.")
        return

    ok = skip_small = skip_pano = fail = 0
    print(f"Found {len(imgs)} JPG/JPEG files. Overwriting originals if resize is needed...")

    for src in imgs:
        try:
            dims = get_dims_via_ffmpeg(ffmpeg_path, src)
            if not dims:
                print(f"SKIP (can't read dims): {src.name}")
                continue

            w, h = dims

            # Skip panoramas
            if w > SKIP_OVER or h > SKIP_OVER:
                print(f"SKIP panorama (>8k): {src.name}  ({w}x{h})")
                skip_pano += 1
                continue

            # Skip if already small enough
            if max(w, h) <= MAX_EDGE:
                print(f"SKIP (<= {MAX_EDGE}): {src.name}  ({w}x{h})")
                skip_small += 1
                continue

            scale = build_scale_filter(w, h, MAX_EDGE)

            # Write to a temp file in the same folder, then replace original
            tmp = src.with_name(f"{src.stem}.__tmp_{uuid.uuid4().hex}{src.suffix}")

            cmd = [
                str(ffmpeg_path),
                "-y",
                "-hide_banner",
                "-loglevel", "error",
                "-i", str(src),
                "-vf", scale,
                "-frames:v", "1",
                # Very high JPEG quality (close to "98%")
                "-q:v", "2",
                # Try to keep metadata when possible
                "-map_metadata", "0",
                str(tmp),
            ]

            code, out, err = run_capture(cmd)
            if code != 0 or not tmp.exists() or tmp.stat().st_size == 0:
                if tmp.exists():
                    tmp.unlink(missing_ok=True)
                raise RuntimeError(err.strip() or out.strip() or "ffmpeg failed")

            os.replace(tmp, src)  # atomic replace on Windows
            print(f"OK  {src.name}  ({w}x{h}) -> resized (max edge {MAX_EDGE}) [OVERWROTE]")
            ok += 1

        except Exception as e:
            print(f"FAIL {src.name}: {e}")
            fail += 1

    print(f"\nDone ✅  OK={ok}  SKIP_small={skip_small}  SKIP_pano={skip_pano}  FAIL={fail}")

if __name__ == "__main__":
    main()

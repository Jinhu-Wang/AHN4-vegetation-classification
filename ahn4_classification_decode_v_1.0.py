#!/usr/bin/env python3
"""
ahn4_classification_decode_v_1.0.py
Attach published per-point class labels (*.cls) to the ORIGINAL AHN4 LAZ tiles.

The *.cls file holds one class id (uint8) per point, in the point order of the
original AHN4 tile, plus a fingerprint of that tile. Decoding checks the
fingerprint, so labels can never be silently attached to a different tile,
version or re-ordered copy: on a mismatch the output is deleted.

HOW TO RUN
  1) Press "Run" (no arguments): edit the CONFIG block below. Every *.cls in
     LABEL_DIR is matched by tile name to ORIGINAL_DIR/<tile>.LAZ (any case)
     and written to OUTPUT_DIR/<tile>_classified.laz.
  2) Command line:
       python3 ahn4_classification_decode_v_1.0.py apply   original.LAZ labels.cls out.laz
       python3 ahn4_classification_decode_v_1.0.py extract original.LAZ labels.cls out.npy
       python3 ahn4_classification_decode_v_1.0.py info    labels.cls
       python3 ahn4_classification_decode_v_1.0.py batch   original_dir label_dir output_dir
  3) From Python:
       import importlib.util, laspy
       spec = importlib.util.spec_from_file_location("dec", "ahn4_classification_decode_v_1.0.py")
       dec = importlib.util.module_from_spec(spec); spec.loader.exec_module(dec)
       labels = dec.load_labels("original/C_27CZ2.LAZ", "C_27CZ2.cls")   # numpy uint8
       # e.g. las = laspy.read("original/C_27CZ2.LAZ"); las.classification = labels

OUTPUT
  "apply" writes a copy of the original tile (same LAS version, point format,
  extra bytes and point order) in which only the classification is replaced.

REQUIREMENTS
  python >= 3.8, numpy, laspy >= 2.0 with LAZ support:  pip install "laspy[lazrs]"

LABEL FILE FORMAT  (AHNCLS01, little-endian)
  offset  size  field
  0       8     magic b"AHNCLS01"
  8       8     uint64 number of points
  16      1     uint8 codec (1 = zlib stream, 2 = xz/lzma stream)
  17      7     reserved (zero)
  24      32    SHA-256 fingerprint of the original tile: for each consecutive
                block of 10,000,000 points (last block shorter), in point order,
                the raw int32 X values, then Y, then Z
  56      ...   compressed stream of <number of points> uint8 class ids
"""
import argparse
import glob
import hashlib
import lzma
import os
import struct
import sys
import time
import zlib

import numpy as np
import laspy

# ============================== CONFIG ===================================
# Used only when the script is started WITHOUT command-line arguments.
# Relative paths are resolved against the folder this script lives in.
ORIGINAL_DIR = "original"   # folder with the original AHN4 tiles (*.LAZ / *.laz)
LABEL_DIR = "."             # folder with the *.cls label files
OUTPUT_DIR = "decoded"      # classified tiles are written here
OUTPUT_EXT = ".laz"         # ".laz" (compressed) or ".las"
OVERWRITE = False           # False: skip tiles whose output already exists
# =========================================================================

MAGIC = b"AHNCLS01"
HEADER = struct.Struct("<8sQB7x32s")  # 56 bytes
CODEC_ZLIB, CODEC_LZMA = 1, 2
HASH_BLOCK = 10_000_000  # part of the file format (fingerprint), do not change
CHUNK = 10_000_000       # points read per step; only affects memory use


def _progress(tag, i, n):
    """\\r counter in a terminal; plain lines every ~10% elsewhere (e.g. VS Code output panel)."""
    if sys.stderr.isatty():
        print(f"\r{tag}{i:,}/{n:,}", end="", file=sys.stderr, flush=True)
    else:
        step = max(n // 10, 1)
        if i >= n or i // step != max(i - CHUNK, 0) // step:
            print(f"{tag}{i:,}/{n:,} ({100 * i // max(n, 1)}%)", file=sys.stderr, flush=True)


def _open_laz(path):
    try:
        return laspy.open(path, laz_backend=laspy.LazBackend.LazrsParallel)
    except Exception:
        return laspy.open(path)


class FingerprintError(Exception):
    pass


def read_header(f):
    raw = f.read(HEADER.size)
    if len(raw) != HEADER.size:
        raise ValueError("file too short to be an AHNCLS01 label file")
    magic, n, codec, digest = HEADER.unpack(raw)
    if magic != MAGIC:
        raise ValueError("not an AHNCLS01 label file")
    if codec not in (CODEC_ZLIB, CODEC_LZMA):
        raise ValueError(f"unknown codec {codec}")
    return n, codec, digest


class LabelReader:
    """Streams the uint8 labels out of a .cls file, `n` at a time, with bounded memory."""

    def __init__(self, f, codec):
        self.f, self.codec, self.buf = f, codec, bytearray()
        self.d = zlib.decompressobj() if codec == CODEC_ZLIB else lzma.LZMADecompressor(format=lzma.FORMAT_XZ)

    def _fill(self):
        if self.codec == CODEC_ZLIB:
            data = self.d.unconsumed_tail or self.f.read(1 << 20)
            if not data:
                return False
            self.buf += self.d.decompress(data, 1 << 26)
        else:
            data = b""
            if self.d.needs_input:
                data = self.f.read(1 << 20)
                if not data:
                    return False
            self.buf += self.d.decompress(data, max_length=1 << 26)
        return True

    def read(self, n):
        while len(self.buf) < n and not self.d.eof and self._fill():
            pass
        out = np.frombuffer(bytes(self.buf[:n]), dtype=np.uint8)
        del self.buf[:n]
        return out


class Fingerprint:
    """SHA-256 over blocks of HASH_BLOCK points (X, then Y, then Z as int32),
    independent of how many points are fed per call."""

    def __init__(self):
        self.h, self.parts, self.size = hashlib.sha256(), [], 0

    def _flush(self, upto):
        xyz = [np.concatenate([p[d] for p in self.parts]) for d in range(3)]
        for d in range(3):
            self.h.update(xyz[d][:upto].tobytes())
        rest = [a[upto:] for a in xyz]
        self.parts, self.size = ([rest] if len(rest[0]) else []), len(rest[0])

    def update(self, pts):
        self.parts.append([np.ascontiguousarray(pts[d], dtype="<i4") for d in ("X", "Y", "Z")])
        self.size += len(pts)
        while self.size >= HASH_BLOCK:
            self._flush(HASH_BLOCK)

    def digest(self):
        if self.size:
            self._flush(self.size)
        return self.h.digest()


def _decode(original, labels, sink):
    """Streams the original tile and the labels side by side, calls
    sink(header, points, labels) per chunk, then checks the fingerprint."""
    with open(labels, "rb") as f, _open_laz(original) as ro:
        n, codec, digest = read_header(f)
        if ro.header.point_count != n:
            raise FingerprintError(f"label file is for {n:,} points, "
                                   f"{os.path.basename(original)} has {ro.header.point_count:,}")
        lr, fp, done = LabelReader(f, codec), Fingerprint(), 0
        for pts in ro.chunk_iterator(CHUNK):
            lab = lr.read(len(pts))
            if len(lab) != len(pts):
                raise ValueError("label stream ended early (corrupt or truncated .cls file)")
            fp.update(pts)
            sink(ro.header, pts, lab)
            done += len(pts)
            _progress("", done, n)
        if fp.digest() != digest:
            raise FingerprintError(f"{os.path.basename(labels)} does not belong to "
                                   f"{os.path.basename(original)} (different tile, version or point order)")


def load_labels(original, labels):
    """Returns the class ids of all points of `original` as a numpy uint8 array (original point order)."""
    parts = []
    _decode(original, labels, lambda h, p, lab: parts.append(lab))
    return np.concatenate(parts) if parts else np.empty(0, np.uint8)


def apply(original, labels, output):
    """Writes `output`: the original tile with the classification from `labels`."""
    os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
    tmp = output + ".part"
    state = {}

    def sink(header, pts, lab):
        if "w" not in state:
            state["w"] = laspy.open(tmp, mode="w", header=header,
                                    do_compress=output.lower().endswith(".laz"))
        pts.classification = lab
        state["w"].write_points(pts)

    try:
        _decode(original, labels, sink)
    except BaseException:
        if "w" in state:
            state["w"].close()
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    state["w"].close()
    os.replace(tmp, output)


def info(labels):
    with open(labels, "rb") as f:
        n, codec, digest = read_header(f)
        print(f"file   : {labels}\npoints : {n:,}\ncodec  : {({1: 'zlib', 2: 'lzma'})[codec]}\n"
              f"sha256 : {digest.hex()}")
        lr, hist, seen = LabelReader(f, codec), np.zeros(256, np.int64), 0
        while seen < n:
            lab = lr.read(min(CHUNK, n - seen))
            if not len(lab):
                raise ValueError("label stream ended early (corrupt or truncated .cls file)")
            hist += np.bincount(lab, minlength=256)
            seen += len(lab)
    for c in np.nonzero(hist)[0]:
        print(f"class {c:3d}: {hist[c]:>14,}  ({100 * hist[c] / n:6.2f}%)")


def _find_original(original_dir, tile):
    hits = [p for p in glob.glob(os.path.join(original_dir, "*"))
            if os.path.splitext(os.path.basename(p))[0].lower() == tile.lower()
            and os.path.splitext(p)[1].lower() in (".laz", ".las")]
    return hits[0] if hits else None


def batch(original_dir, label_dir, output_dir, ext=".laz", overwrite=False):
    """Decodes every *.cls in label_dir against original_dir/<tile>.LAZ. Returns number of failures."""
    cls_files = sorted(glob.glob(os.path.join(label_dir, "*.cls")))
    if not cls_files:
        print(f"no *.cls files in {os.path.abspath(label_dir)}", file=sys.stderr)
        return 1
    failed = 0
    for k, cls in enumerate(cls_files, 1):
        tile = os.path.splitext(os.path.basename(cls))[0]
        out = os.path.join(output_dir, tile + "_classified" + ext)
        print(f"=== [{k}/{len(cls_files)}] {tile}", file=sys.stderr, flush=True)
        orig = _find_original(original_dir, tile)
        if orig is None:
            print(f"    SKIPPED: no {tile}.LAZ in {os.path.abspath(original_dir)}", file=sys.stderr)
            failed += 1
            continue
        if os.path.exists(out) and not overwrite:
            print(f"    SKIPPED: {out} exists (set OVERWRITE = True to redo)", file=sys.stderr)
            continue
        t0 = time.time()
        try:
            apply(orig, cls, out)
            print(f"    wrote {out} in {time.time() - t0:,.0f} s", file=sys.stderr, flush=True)
        except (FingerprintError, ValueError) as e:
            print(f"    FAILED: {e}. Nothing written.", file=sys.stderr)
            failed += 1
    print(f"done: {len(cls_files) - failed} ok, {failed} failed/skipped", file=sys.stderr)
    return failed


def main():
    if len(sys.argv) == 1:
        here = os.path.dirname(os.path.abspath(__file__))
        r = lambda q: os.path.join(here, q)
        sys.exit(1 if batch(r(ORIGINAL_DIR), r(LABEL_DIR), r(OUTPUT_DIR), OUTPUT_EXT, OVERWRITE) else 0)

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    s = p.add_subparsers(dest="cmd", required=True)
    a_ = s.add_parser("apply", help="write classified LAZ/LAS")
    a_.add_argument("original"); a_.add_argument("labels"); a_.add_argument("output")
    x_ = s.add_parser("extract", help="write labels as .npy")
    x_.add_argument("original"); x_.add_argument("labels"); x_.add_argument("output")
    i_ = s.add_parser("info", help="summary of a .cls file")
    i_.add_argument("labels")
    b_ = s.add_parser("batch", help="decode every *.cls in a folder")
    b_.add_argument("original_dir"); b_.add_argument("label_dir"); b_.add_argument("output_dir")
    b_.add_argument("--las", action="store_true", help="write uncompressed .las")
    b_.add_argument("--overwrite", action="store_true")
    a = p.parse_args()
    try:
        if a.cmd == "apply":
            apply(a.original, a.labels, a.output)
            print(f"wrote {a.output}", file=sys.stderr)
        elif a.cmd == "extract":
            np.save(a.output, load_labels(a.original, a.labels))
            print(f"wrote {a.output}", file=sys.stderr)
        elif a.cmd == "info":
            info(a.labels)
        else:
            sys.exit(1 if batch(a.original_dir, a.label_dir, a.output_dir,
                                ".las" if a.las else ".laz", a.overwrite) else 0)
    except FingerprintError as e:
        sys.exit(f"FINGERPRINT MISMATCH: {e}. Nothing written.")
    except ValueError as e:
        sys.exit(f"ERROR: {e}")


if __name__ == "__main__":
    main()

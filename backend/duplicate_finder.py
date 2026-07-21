import cv2
import numpy as np
from typing import List, Dict, Tuple

def compute_dhash(image_bytes: bytes, hash_size: int = 8) -> int:
    """
    Computes a 64-bit Difference Hash (dHash) for an image.
    dHash is invariant to scaling, aspect ratio, and minor brightness shifts.
    """
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return 0
    
    # Resize to (hash_size + 1, hash_size)
    resized = cv2.resize(img, (hash_size + 1, hash_size), interpolation=cv2.INTER_AREA)
    # Compare adjacent pixels
    diff = resized[:, 1:] > resized[:, :-1]
    
    # Convert boolean array to integer hash
    hash_val = 0
    for idx, val in enumerate(diff.flatten()):
        if val:
            hash_val |= (1 << idx)
    return hash_val


def hamming_distance(h1: int, h2: int) -> int:
    """
    Counts bit differences between two 64-bit integers.
    """
    return bin(h1 ^ h2).count('1')


def similarity_percentage(h1: int, h2: int, hash_size: int = 8) -> float:
    """
    Converts Hamming distance to a 0.0 - 100.0% similarity score.
    """
    max_bits = hash_size * hash_size
    dist = hamming_distance(h1, h2)
    similarity = max(0.0, (1.0 - (dist / float(max_bits))) * 100.0)
    return round(similarity, 1)


def find_duplicates_in_batch(files_data: List[Tuple[str, bytes]], threshold_pct: float = 85.0) -> List[Dict]:
    """
    Compares all images in a batch and flags pairs with similarity >= threshold_pct.
    files_data: List of (filename, image_bytes)
    """
    hashes = []
    for idx, (filename, contents) in enumerate(files_data):
        h = compute_dhash(contents)
        hashes.append((idx, filename, h))

    duplicate_pairs = []
    n = len(hashes)
    for i in range(n):
        for j in range(i + 1, n):
            idx1, name1, h1 = hashes[i]
            idx2, name2, h2 = hashes[j]
            if h1 == 0 or h2 == 0:
                continue
            sim = similarity_percentage(h1, h2)
            if sim >= threshold_pct:
                duplicate_pairs.append({
                    "index_a": idx1,
                    "filename_a": name1,
                    "index_b": idx2,
                    "filename_b": name2,
                    "similarity": sim
                })

    return duplicate_pairs

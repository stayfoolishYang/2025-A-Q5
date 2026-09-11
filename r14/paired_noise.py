"""Order-independent common-random-number noise for paired sampled worlds."""
import hashlib
from conditional_noise import ConditionalNoise,weights
class PairedNoise(ConditionalNoise):
    def __init__(self,source_position,history,seed):
        self.seed=int(seed);super().__init__(source_position,history,seed)
    def value(self,point):
        total=0.
        for key,w in weights(point).items():
            if key in self.grid:value=self.grid[key]
            else:
                digest=hashlib.blake2b(f'{self.seed}:{key[0]}:{key[1]}'.encode(),digest_size=8).digest()
                value=2*int.from_bytes(digest,'big')/2**64-1
            total+=w*value
        return total

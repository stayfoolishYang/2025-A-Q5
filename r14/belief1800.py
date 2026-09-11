"""Correct target-domain prior; preserve earlier frozen implementations."""
from belief_fast import DiscoveryBelief as Original
class DiscoveryBelief(Original):
    def __init__(self,power=17,seed=14001):
        super().__init__(power,seed)
        self.states[:,:2]*=.9

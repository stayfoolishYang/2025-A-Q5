"""Q3-only candidate: discovery misses do not spend localization retries."""
from phase_audit import TaggedSolver


class ActiveFailureSolver(TaggedSolver):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.mixed or self.policy != 'P3':
            raise ValueError('Active-failure candidate is restricted to Q3/P3')

    def localize(self, c, one_step=False):
        previous = getattr(self, '_active_localization', False)
        self._active_localization = True
        try:
            return super().localize(c, one_step)
        finally:
            self._active_localization = previous

    def measure(self, c, p):
        previous = self.tracks.get(c, {}).get('negatives', 0)
        result = super().measure(c, p)
        if (not getattr(self, '_active_localization', False) and c in self.tracks
                and self.history[c][-1][1] == 'no_signal'):
            self.tracks[c]['negatives'] = previous
        return result

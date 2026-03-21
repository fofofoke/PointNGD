"""Statistics tracker for automation runs."""
import time
import os
from datetime import datetime


class StatsTracker:
    """Track and export automation statistics."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.start_time = None
        self.total_iterations = 0
        self.successful = 0
        self.failed_mp = 0
        self.errors = 0
        self.deaths = 0
        self.stuck_count = 0
        self.mp_history = []  # list of {level, mp, iteration}
        self.level_times = []  # list of {level, time_seconds, iteration}

    def start(self):
        self.start_time = time.time()

    def record_iteration(self):
        self.total_iterations += 1

    def record_success(self):
        self.successful += 1

    def record_mp_fail(self, level, actual_mp, required_mp, iteration):
        self.failed_mp += 1
        self.mp_history.append({
            "level": level, "actual_mp": actual_mp,
            "required_mp": required_mp, "iteration": iteration,
            "result": "fail",
        })

    def record_mp_pass(self, level, mp, iteration):
        self.mp_history.append({
            "level": level, "actual_mp": mp,
            "required_mp": mp, "iteration": iteration,
            "result": "pass",
        })

    def record_error(self):
        self.errors += 1

    def record_death(self):
        self.deaths += 1

    def record_stuck(self):
        self.stuck_count += 1

    def record_level_up(self, level, iteration):
        elapsed = time.time() - self.start_time if self.start_time else 0
        self.level_times.append({
            "level": level, "elapsed": elapsed, "iteration": iteration,
        })

    def elapsed_seconds(self):
        if self.start_time is None:
            return 0
        return time.time() - self.start_time

    def elapsed_str(self):
        s = int(self.elapsed_seconds())
        h, s = divmod(s, 3600)
        m, s = divmod(s, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    def success_rate(self):
        if self.total_iterations == 0:
            return 0.0
        return self.successful / self.total_iterations * 100

    def mp_distribution(self):
        """Get MP distribution per level. Returns dict {level: {mp_value: count}}."""
        dist = {}
        for entry in self.mp_history:
            lv = entry["level"]
            mp = entry["actual_mp"]
            if lv not in dist:
                dist[lv] = {}
            dist[lv][mp] = dist[lv].get(mp, 0) + 1
        return dist

    def summary_text(self):
        """Generate a human-readable summary."""
        lines = [
            "=" * 50,
            "  LC AB - Statistics Report",
            f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "=" * 50,
            "",
            f"  Elapsed Time     : {self.elapsed_str()}",
            f"  Total Iterations : {self.total_iterations}",
            f"  Successful       : {self.successful}",
            f"  Failed (MP)      : {self.failed_mp}",
            f"  Errors           : {self.errors}",
            f"  Deaths           : {self.deaths}",
            f"  Stuck Count      : {self.stuck_count}",
            f"  Success Rate     : {self.success_rate():.1f}%",
            "",
        ]

        # MP distribution
        dist = self.mp_distribution()
        if dist:
            lines.append("-" * 50)
            lines.append("  MP Distribution by Level:")
            lines.append("-" * 50)
            for lv in sorted(dist.keys()):
                mp_counts = dist[lv]
                parts = [f"MP={mp}:{count}" for mp, count in sorted(mp_counts.items())]
                lines.append(f"  Level {lv}: {', '.join(parts)}")
            lines.append("")

        # Level-up times
        if self.level_times:
            lines.append("-" * 50)
            lines.append("  Recent Level-Up Times:")
            lines.append("-" * 50)
            for entry in self.level_times[-20:]:
                t = int(entry["elapsed"])
                h, t = divmod(t, 3600)
                m, s = divmod(t, 60)
                lines.append(
                    f"  Iter #{entry['iteration']:>4d}  Lv{entry['level']}  "
                    f"at {h:02d}:{m:02d}:{s:02d}"
                )
            lines.append("")

        lines.append("=" * 50)
        return "\n".join(lines)

    def save_to_file(self, path="stats.txt"):
        """Save statistics summary to a text file."""
        text = self.summary_text()
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def append_to_file(self, path="stats_log.txt"):
        """Append current stats to a cumulative log file."""
        text = self.summary_text()
        with open(path, "a", encoding="utf-8") as f:
            f.write(text + "\n\n")
        return path

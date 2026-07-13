#!/usr/bin/env python3
"""Compatibility entry point for the target preflight."""
from pathlib import Path
from collect_pa_news import Collector, load_config

if __name__ == '__main__':
    Collector(load_config(Path('config/pa_news.yml'))).preflight()

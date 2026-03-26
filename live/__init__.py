from .bilibili import BilibiliLive


def create_live(config, **callbacks):
    """Create live module instance based on platform setting."""
    platform = config.get('platform', 'bilibili')
    if platform == 'bilibili':
        return BilibiliLive(config, **callbacks)
    raise ValueError(f'Unknown platform: {platform}')

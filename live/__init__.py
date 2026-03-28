from .bilibili import BilibiliLive
from .youtube import YouTubeLive


def create_live(config, **callbacks):
    """Create live module instance based on platform setting.

    Config is expected to have nested platform-specific dicts:
        {"platform": "bilibili", "bilibili": {...}, "youtube": {...}, "auto_forward": true, ...}
    Shared keys (auto_forward, forward_gifts) are merged into the platform dict.
    """
    platform = config.get('platform', 'bilibili')
    platform_config = dict(config.get(platform, {}))

    if platform == 'bilibili':
        return BilibiliLive(platform_config, **callbacks)
    if platform == 'youtube':
        return YouTubeLive(platform_config, **callbacks)
    raise ValueError(f'Unknown platform: {platform}')

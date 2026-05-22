from .jd import JDCrawler
from .taobao import TaobaoCrawler

CRAWLER_MAP = {
    "taobao": TaobaoCrawler,
    "jd": JDCrawler,
}

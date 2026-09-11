from django.contrib.sitemaps import Sitemap
from .models import HardwareArticle

class HardwareSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.7
    protocol = "https"

    def items(self):
        return HardwareArticle.objects.filter(status="published")

    def lastmod(self, article):
        return article.last_updated_at

    def location(self, article):
        return f"/hardware/article.html?id={article.id}"

    def get_urls(self, page=1, site=None, protocol=None):
        protocol = "https"
        from django.contrib.sites.models import Site as DjangoSite
        site = DjangoSite(domain="coreripper.site", name="CoreRipper")
        return super().get_urls(page=page, site=site, protocol=protocol)

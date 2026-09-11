from django.contrib.sitemaps import Sitemap

from .models import Post


class PostSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.7

    def items(self):
        return Post.objects.filter(is_published=True)

    def lastmod(self, post):
        return post.updated_at

    def location(self, post):
        return f"/blog/post.html?slug={post.slug}"

from django.contrib.syndication.views import Feed

from .models import Post


class LatestPostsFeed(Feed):
    title = "CoreRipper Blog"
    link = "/blog/"
    description = "Tutorials and articles on programming, Linux, networking, AI, and cybersecurity from CoreRipper."

    def items(self):
        return Post.objects.filter(is_published=True)[:20]

    def item_title(self, post):
        return post.title

    def item_description(self, post):
        return post.excerpt

    def item_link(self, post):
        return f"/blog/post.html?slug={post.slug}"

    def item_pubdate(self, post):
        return post.published_at

    def item_author_name(self, post):
        return post.author_name

    def item_categories(self, post):
        return [post.category.name]

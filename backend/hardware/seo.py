"""Reusable JSON-LD builders for the SEO layer  backend-only for now, since
this phase deliberately builds no hardware frontend pages yet ("prepare
architecture, don't implement UI" per the spec). These return plain dicts a
future template can `json.dumps()` straight into a `<script
type="application/ld+json">` tag, exactly like news/post.html's
`injectSeoTags()` does client-side today  when a hardware article page
gets built, it can fetch `GET /api/hardware/articles/<id>/`, which already
includes this under `seo_jsonld`, instead of duplicating this logic.

`FRONTEND_ARTICLE_PATH` mirrors news' `news/post.html?id=<id>` convention so
the canonical URL is already correct the moment a matching frontend page
exists at that path  not a placeholder guess, a deliberate reservation of
that URL shape.
"""
FRONTEND_ARTICLE_PATH = "/hardware/article.html?id={id}"


def build_breadcrumb_jsonld(article, category_label, site_root):
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home", "item": f"{site_root}/index.html"},
            {"@type": "ListItem", "position": 2, "name": "Hardware", "item": f"{site_root}/hardware.html"},
            {
                "@type": "ListItem", "position": 3, "name": category_label,
                "item": f"{site_root}/hardware.html?category={article.category}",
            },
            {
                "@type": "ListItem", "position": 4, "name": article.title,
                "item": f"{site_root}{FRONTEND_ARTICLE_PATH.format(id=article.id)}",
            },
        ],
    }


def build_article_jsonld(article, site_root):
    canonical = f"{site_root}{FRONTEND_ARTICLE_PATH.format(id=article.id)}"
    return {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": article.title,
        "description": article.ai_summary,
        "author": {"@type": "Organization", "name": "CoreRipper"},
        "publisher": {"@type": "Organization", "name": "CoreRipper"},
        "datePublished": article.published_at.isoformat() if article.published_at else None,
        "dateModified": article.last_updated_at.isoformat() if article.last_updated_at else None,
        "mainEntityOfPage": canonical,
    }

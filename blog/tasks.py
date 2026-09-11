"""Blog Celery tasks. Currently only the Intelligent auto-editor pass
registered via data migration (see blog/migrations), same hand-started
worker/beat caveat as the rest of the project."""
from celery import shared_task


@shared_task
def auto_edit_blog():
    """Refresh due published blog posts: image + SEO always; body only for
    posts flagged auto_managed (hand-written posts keep their prose). See
    core.intel.auto_editor.refresh_blog_post."""
    from core.intel.auto_editor import run_auto_edit

    return run_auto_edit("blog")

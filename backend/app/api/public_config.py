from fastapi import APIRouter

from app.core.config import settings

router = APIRouter()


@router.get('/public/config')
def public_config():
    return {
        'deployment_mode': settings.DEPLOYMENT_MODE,
        'brand': {
            'product_name': settings.BRAND_PRODUCT_NAME,
            'support_email': settings.BRAND_SUPPORT_EMAIL,
            'public_site_url': settings.PUBLIC_SITE_URL,
            'app_url': settings.PUBLIC_APP_URL,
        },
        'analytics': {'ga_id': settings.ANALYTICS_GA_ID, 'ahrefs_key': settings.ANALYTICS_AHREFS_KEY},
    }

from aiogram.filters import BaseFilter
from aiogram.types import Message, CallbackQuery
from config import settings
from database.crud import is_admin_user, get_admin_permissions


class AdminFilter(BaseFilter):
    async def __call__(self, obj: Message | CallbackQuery) -> bool:
        if obj.from_user.id in settings.admin_ids:
            return True
        return await is_admin_user(obj.from_user.id)


class SuperAdminFilter(BaseFilter):
    async def __call__(self, obj: Message | CallbackQuery) -> bool:
        return obj.from_user.id in settings.admin_ids


class PermissionFilter(BaseFilter):
    def __init__(self, permission: str) -> None:
        self.permission = permission

    async def __call__(self, obj: Message | CallbackQuery) -> bool:
        if obj.from_user.id in settings.admin_ids:
            return True
        perms = await get_admin_permissions(obj.from_user.id)
        return perms is not None and perms.get(self.permission, False)

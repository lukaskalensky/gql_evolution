from __future__ import annotations

import strawberry

from src.ServiceDefinitions.ServiceContext import ServiceContext


class ApplicationInfo(strawberry.Info):
    @property
    def ServiceCtx(self) -> ServiceContext:
        context = self.context

        service_ctx = getattr(context, 'ServiceCtx', None)
        if isinstance(service_ctx, ServiceContext):
            return service_ctx

        # if isinstance(context, ServiceContext):
        #     return context

        # if isinstance(context, dict):
        #     service_ctx = context.get('ServiceCtx') or context.get('service_ctx')
        #     if isinstance(service_ctx, ServiceContext):
        #         return service_ctx

        raise RuntimeError('GraphQL context does not contain ServiceContext')

    @property
    def loaders(self):
        return self.ServiceCtx.loaders

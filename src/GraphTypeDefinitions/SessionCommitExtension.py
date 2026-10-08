from __future__ import annotations

import inspect
import typing

from strawberry.extensions import SchemaExtension

from src.Dataloaders import LoaderMap
from src.DBDefinitions.runtime import Database
from src.ServiceDefinitions.ServiceContext import ServiceContext


async def _maybe_await(value: typing.Any) -> typing.Any:
    if inspect.isawaitable(value):
        return await value
    return value


class SessionCommitExtension(SchemaExtension):
    """Creates one DB session per GraphQL operation and commits atomically.

    The extension has a no-argument constructor so it can be registered as
    `SessionCommitExtension` in `schema.extensions`.

    It obtains factories from the GraphQL context when available:
    - context.resolve_session_maker()
    - context.resolve_loaders(session)
    - context["session_maker_factory"]
    - context["loaders_factory"]

    If the context does not provide them, it falls back to Database().session_maker
    and LoaderMap(session).
    """

    async def _get_session_maker(self, context: typing.Any) -> typing.Any:
        resolver = getattr(context, 'resolve_session_maker', None)
        if resolver is not None:
            return await _maybe_await(resolver())

        factory = None
        get = getattr(context, 'get', None)
        if get is not None:
            factory = get('session_maker_factory')

        if factory is not None:
            return await _maybe_await(factory())

        return Database().session_maker

    async def _create_loaders(self, context: typing.Any, session: typing.Any) -> typing.Any:
        resolver = getattr(context, 'resolve_loaders', None)
        if resolver is not None:
            return await _maybe_await(resolver(session))

        factory = None
        get = getattr(context, 'get', None)
        if get is not None:
            factory = get('loaders_factory')

        if factory is not None:
            return await _maybe_await(factory(session))

        return LoaderMap(session)

    def _get_operation_type(self) -> str | None:
        operation = getattr(self.execution_context, 'operation', None)
        if operation is None:
            return None

        operation_type = getattr(operation, 'operation', None)
        if operation_type is None:
            return None

        return getattr(operation_type, 'value', operation_type)

    async def on_operation(self):
        context = self.execution_context.context
        async_session_maker = await self._get_session_maker(context)

        async with async_session_maker() as session:
            try:
                context['session'] = session
                context.setdefault('errors', [])

                loaders = await self._create_loaders(context, session)
                context['loaders'] = loaders

                request = context.get('request')
                user = context.get('user', getattr(getattr(request, 'state', None), 'user', None))
                ug_client = context.get('ug_client')

                service_ctx = ServiceContext(
                    loaders=loaders,
                    request=request,
                    user=user,
                    ug_client=ug_client,
                    session=session,
                )

                context['ServiceCtx'] = service_ctx
                context['service_ctx'] = service_ctx

                yield

                operation_type = self._get_operation_type() or 'mutation'
                errors = context.get('errors', [])

                if errors:
                    await session.rollback()
                    print('Rollback session due to error flag', flush=True)
                elif operation_type == 'mutation':
                    await session.commit()
                    print('Commit session', flush=True)
                else:
                    await session.rollback()
                    print('Rollback read-only operation', flush=True)

            except Exception as e:
                errors = context.setdefault('errors', [])
                errors.append(
                    {
                        'msg': f'Unexpected error during operation: {e}',
                        'code': '43b027da-d073-4fac-8881-3353609f2bcd',
                        '_input': {},
                    }
                )
                await session.rollback()
                print(f'Exception during operation {e}, doing rollback', flush=True)
                raise
        print(f'Session closed for {operation_type}', flush=True)

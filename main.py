from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from strawberry.fastapi import GraphQLRouter

from src.DBDefinitions.runtime import Database, DatabaseSettings
from src.GraphTypeDefinitions.GraphQLContext import GraphQLContext
from src.GraphTypeDefinitions.schema import schema


@asynccontextmanager
async def lifespan(app: FastAPI):
    await Database().start(DatabaseSettings())
    try:
        yield
    finally:
        await Database().stop()


async def get_gql_context(request: Request):
    return GraphQLContext(
        request=request,
        session_maker_factory=lambda: Database().session_maker,
    )


app = FastAPI(
    title='Event demo federated GraphQL endpoint',
    lifespan=lifespan,
)
app.include_router(GraphQLRouter(schema, context_getter=get_gql_context), prefix='/gql')

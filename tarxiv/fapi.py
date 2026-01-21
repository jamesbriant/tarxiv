from fastapi import FastAPI, Header, HTTPException, Depends, Body, Request
from typing import Annotated
from pydantic import BaseModel

# from .routers import test
from .database import TarxivDB
from .utils import TarxivModule

from tarxiv.utils import PRINT, LOGFILE, DATABASE

DEBUG = True
SCRIPT_NAME = "tarxiv_api"
REPORTING_MODE = PRINT | LOGFILE | DATABASE


class TarxivAPI(TarxivModule):  # inherit from TarxivModule!!
    """API module for server requests to the tarxiv database."""

    def __init__(self, script_name, reporting_mode, debug=False):
        super().__init__(
            script_name=script_name,
            module="fapi",
            reporting_mode=reporting_mode,
            debug=debug,
        )
        self.debug = debug

    def start_server(self):
        status = {"status": "starting fastapi server"}
        self.logger.info(status, extra=status)

        self.app = FastAPI(
            title="TarXiv FastAPI",
            debug=self.debug,
        )

        # List routers here
        # self.app.include_router(test.router)

        status = {"status": "setting up fastapi application"}
        self.logger.info(status, extra=status)

        return self.app


tarxiv_api = TarxivAPI(SCRIPT_NAME, REPORTING_MODE, False)
app = tarxiv_api.start_server()
logger = tarxiv_api.logger

txv_db = TarxivDB("tns", "api", SCRIPT_NAME, REPORTING_MODE, DEBUG)
valid_operators = ["<", ">", "=", "<=", ">=", "IN", "LIKE"]

SearchCondition = dict[str, str | float | list[str | float]]


class SearchQuery(BaseModel):
    """Docstring for SearchQuery

    Example 1:
    ----------
    ```
    search = {
        "redshift": [{
            "value": 0.025,
            "operator": "<"}],
        "peak_mag": [
            {"value": 14.5,
            "operator": ">"},
            {"filter": ["g", "v"],
            "operator": "IN"}],
        "object_type": [
            {"value": "SN",
            "operator": "="}]
    }
    ```

    Example 2:
    ----------
    ```
    search = {
        "discovery_date": [
        {"value": "2025-05-20",
        "operator": ">"}],
        "reporting_group": [
            {"value": ["ATLAS", "ASAS-SN"],
            "operator": "IN"}]
    }
    ```
    """

    redshift: list[SearchCondition] | None = None
    peak_mag: list[SearchCondition] | None = None
    object_type: list[SearchCondition] | None = None
    discovery_date: list[SearchCondition] | None = None
    reporting_group: list[SearchCondition] | None = None

    def items(self):
        d = {key: value for key, value in self.__dict__.items() if value is not None}
        return d.items()


# Dependency enables token verification for routes
async def verify_token(request: Request):
    # TODO: implement actual authentication
    token = request.headers.get("Authorization")
    if not token:
        raise HTTPException(status_code=401, detail="Authorization token missing.")
    if token != "TOKEN":
        raise HTTPException(status_code=401, detail="Invalid token")
    return token


@app.get("/")
async def index() -> dict[str, str]:
    return {"status": "TarXiv FastAPI is running"}


# # Two version of route to handle optional forward slash, prevents 307 redirect
# @app.post(
#     "/get_object_meta/", dependencies=[Depends(verify_token)], include_in_schema=False
# )
# @app.post("/get_object_meta", dependencies=[Depends(verify_token)])
# async def get_object_meta_empty() -> dict[str, str]:
#     raise HTTPException(status_code=400, detail="obj_name parameter is required.")


@app.post("/get_object_meta/{obj_name}")
async def get_object_meta(
    obj_name: str,
    request: Request,
    token: Annotated[str, Depends(verify_token)],
):
    # Start log
    log = {
        "query_type": "meta",
        "query_ip": request.client.host,
        "token": token,
        "obj_name": obj_name,
    }
    logger.info(log, extra=log)
    if not obj_name:
        raise HTTPException(status_code=400, detail="obj_name parameter is required.")
    result = txv_db.get(obj_name, "objects")
    return result


# # Two version of route to handle optional forward slash, prevents 307 redirect
# @app.post(
#     "/get_object_lc/", dependencies=[Depends(verify_token)], include_in_schema=False
# )
# @app.post("/get_object_lc", dependencies=[Depends(verify_token)])
# async def get_object_lc_empty() -> dict[str, str]:
#     raise HTTPException(status_code=400, detail="obj_name parameter is required.")


# @app.post("/get_object_lc/{obj_name}", dependencies=[Depends(verify_token)])
@app.post("/get_object_lc/{obj_name}")
async def get_object_lc(
    obj_name: str,
    request: Request,
    token: Annotated[str, Depends(verify_token)],
):
    # Start log
    log = {
        "query_type": "lightcurves",
        "query_ip": request.client.host,
        "token": token,
        "obj_name": obj_name,
    }
    logger.info(log, extra=log)
    if not obj_name:
        raise HTTPException(status_code=400, detail="obj_name parameter is required.")
    result = txv_db.get(obj_name, "lightcurves")
    return result


# @app.post("/search_objects/", dependencies=[Depends(verify_token)])
# @app.post(
#     "/search_objects", dependencies=[Depends(verify_token)], include_in_schema=False
# )
@app.post("/search_objects/")
@app.post("/search_objects", include_in_schema=False)
async def search_objects(
    search: Annotated[SearchQuery, Body()],
    request: Request,
    token: Annotated[str, Depends(verify_token)],
):
    # Start log
    log = {
        "query_type": "search",
        "query_ip": request.client.host,
        "token": token,
        "search_params": search,
    }
    logger.info(log, extra=log)
    # Build query
    query_str = "SELECT meta().id AS `obj_name` FROM tarxiv.tns.objects WHERE 1=1 AND "
    condition_list = []
    # Add restrictions from search fields, then append search params to query
    for field, condition in search.items():
        condition_str = await build_condition(field, condition)
        condition_list.append(condition_str)

    # Append full condition string to query string
    full_condition_string = " AND ".join(condition_list)
    query_str += full_condition_string
    # Return results
    result = txv_db.query(query_str)
    result = [r["obj_name"] for r in result]
    return result


async def build_condition(field, condition):
    # Start condition_string
    condition_str = f"ANY `{field[0]}` IN `{field}` SATISFIES "
    predicates = []
    # Each query has a number of parameters (usually just value, but peak mag can search on filter/mjd also)
    for param in condition:
        # First check value fields
        if "value" in param.keys():
            prd_str = await build_predicate(
                field, "value", param["operator"], param["value"]
            )
        elif "filter" in param.keys():
            prd_str = await build_predicate(
                field, "filter", param["operator"], param["filter"]
            )
        elif "mjd" in param.keys():
            prd_str = await build_predicate(
                field, "mjd", param["operator"], param["mjd"]
            )
        else:
            raise ValueError(f"bad search option {param}")
        # Add predicate to condition
        predicates.append(prd_str)

    return condition_str + "AND ".join(predicates) + "END "


async def build_predicate(field_name, search_field, operator, search_value):
    # Check valid operators
    # if operator not in valid_operators:
    #     raise ValueError(f"bad operator {operator}")
    # Simple check against SQL injection, allow max two words in query string, semicolons or comment str
    if isinstance(search_value, str):
        if any(char in search_value for char in [";", "/*", "*/", "--"]):
            raise ValueError(f"search field contains invalid characters {search_value}")
    if isinstance(search_value, list):
        for item in search_value:
            if any(char in str(item) for char in [";", "/*", "*/", "--"]):
                raise ValueError(f"search field contains invalid characters {item}")
    # Format predicate search value
    if isinstance(search_value, int) or isinstance(search_value, float):
        value_str = str(search_value)
    elif isinstance(search_value, str):
        value_str = f"'{search_value}'"
    elif isinstance(search_value, list):
        value_str = str(search_value)
    else:
        raise ValueError(f"bad search value {search_value}")
    # Build predicate
    predicate = f"`{field_name[0]}`.`{search_field}` {operator} {value_str} "
    return predicate

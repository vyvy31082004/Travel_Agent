from typing import Optional

from services.excursion_service import (
    search_attractions,
    fetch_attraction_details ,
    fetch_attraction_reviews,
)


def register_excursion_tools(mcp):
    @mcp.tool()
    def search_attractions_tool(
        location: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        sort_by: str = "trending",
        page: int = 1,
        type_filters: Optional[str] = None,
        price_filters: Optional[str] = None,
        ufi_filters: Optional[str] = None,
        label_filters: Optional[str] = None,
        limit: int = 10,
    ) -> list[dict]:
        """
        Search trip by location, start_date, end_date, sort_by, page, type_filters, price_filters, ufi_filters, label_filters, and limit.
        """
        return search_attractions(
            location=location,
            start_date=start_date,
            end_date=end_date,
            sort_by=sort_by,
            page=page,
            type_filters=type_filters,)
    @mcp.tool()
    def fetch_attraction_details_tool(
        slug:  str,
    ) -> dict:
        """
        Fetch attraction details by slug.
        """
        return fetch_attraction_details(
            slug=slug,
        )
    @mcp.tool()
    def fetch_attraction_reviews_tool(
        id: str,
    ) -> dict:
        """
        Get guest reviews for attractions by id.
        Use when user asks for reviews/đánh giá of tours or attractions.
        """
        return fetch_attraction_reviews(
            id=id,
        )
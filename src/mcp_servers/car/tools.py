from datetime import datetime

from services.car_service import (
    search_cars,
    get_car_details,
)


def register_car_tools(mcp):

    @mcp.tool()
    def search_cars_tool(
        start_ms: int | str,
        end_ms: int | str,
        address: str,
        user_needs: str, 
        limit: int = 10,
        min_price: int = 0,
        max_price: int = 0,
    ) -> dict:
        """ 
        Search Mioto rental cars by address and rental time.

        start_ms/end_ms can be Unix milliseconds or datetime strings in
        "YYYY-MM-DD HH:MM" format. If the user omits the year, use the current year.

        Each car includes: car_id, Tên xe, Giá sau giảm, Giá gốc, Hộp số,
        Số chỗ, Nhiên liệu, Địa chỉ, Rating, Số chuyến, Tags, Ảnh, Link.
        """
        if not address:
            return {"error": "Bạn cần cung cấp địa chỉ.", "cars": [], "count": 0}
        if not start_ms:
            start_ms = datetime.now().timestamp()
        if not end_ms:
            end_ms = datetime.now().timestamp()
        cars = search_cars(start_ms=start_ms, end_ms=end_ms, address=address, user_needs=user_needs, limit=limit, min_price=min_price, max_price=max_price)
        return {"count": len(cars), "cars": cars}

    @mcp.tool()
    def get_car_details_tool(car_name: str, car_id: str) -> dict:
        """
        Get details of a  car by car_id.

        """
        if not car_name:
            return {"error": "Bạn cần cung cấp tên xe.", "car": {}}
        if not car_id:
            return {"error": "Bạn cần cung cấp mã xe.", "car": {}}
        return get_car_details(car_name, car_id)
 
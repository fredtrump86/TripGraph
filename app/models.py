from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TripRequest(StrictModel):
    """与参考项目一致的旅行规划请求。"""

    city: str = Field(min_length=1, max_length=40)
    start_date: date
    end_date: date
    travel_days: int = Field(ge=1, le=30)
    transportation: str = Field(min_length=1, max_length=30)
    accommodation: str = Field(min_length=1, max_length=30)
    preferences: list[str] = Field(default_factory=list, max_length=10)
    free_text_input: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def validate_dates(self) -> TripRequest:
        if self.end_date < self.start_date:
            raise ValueError("结束日期不能早于开始日期")
        actual_days = (self.end_date - self.start_date).days + 1
        if actual_days > 30:
            raise ValueError("旅行天数不能超过30天")
        if self.travel_days != actual_days:
            raise ValueError("旅行天数必须与日期范围一致")
        return self


class Location(StrictModel):
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)


class Attraction(StrictModel):
    name: str
    address: str
    location: Location
    visit_duration: int = Field(ge=15, le=720)
    description: str
    category: str = "景点"
    rating: float | None = Field(default=None, ge=0, le=5)
    photos: list[str] = Field(default_factory=list)
    poi_id: str = ""
    image_url: str | None = None
    ticket_price: int = Field(default=0, ge=0)


class Meal(StrictModel):
    type: Literal["breakfast", "lunch", "dinner", "snack"]
    name: str
    address: str | None = None
    location: Location | None = None
    description: str | None = None
    estimated_cost: int = Field(default=0, ge=0)


class Hotel(StrictModel):
    name: str
    address: str = ""
    location: Location | None = None
    price_range: str = ""
    rating: str = ""
    distance: str = ""
    type: str = ""
    estimated_cost: int = Field(default=0, ge=0)


class WeatherInfo(StrictModel):
    date: date
    day_weather: str = ""
    night_weather: str = ""
    day_temp: int = 0
    night_temp: int = 0
    wind_direction: str = ""
    wind_power: str = ""

    @field_validator("day_temp", "night_temp", mode="before")
    @classmethod
    def parse_temperature(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.replace("°C", "").replace("℃", "").replace("°", "").strip()
            try:
                return int(normalized)
            except ValueError:
                return 0
        return value


class DayPlan(StrictModel):
    date: date
    day_index: int = Field(ge=0, le=29)
    description: str
    transportation: str
    accommodation: str
    hotel: Hotel | None = None
    attractions: list[Attraction] = Field(default_factory=list)
    meals: list[Meal] = Field(default_factory=list)


class Budget(StrictModel):
    total_attractions: int = Field(default=0, ge=0)
    total_hotels: int = Field(default=0, ge=0)
    total_meals: int = Field(default=0, ge=0)
    total_transportation: int = Field(default=0, ge=0)
    total: int = Field(default=0, ge=0)


class TripPlan(StrictModel):
    city: str
    start_date: date
    end_date: date
    days: list[DayPlan]
    weather_info: list[WeatherInfo] = Field(default_factory=list)
    overall_suggestions: str
    budget: Budget | None = None


class ResearchBundle(StrictModel):
    attractions: list[Attraction] = Field(default_factory=list)
    weather: list[WeatherInfo] = Field(default_factory=list)
    hotels: list[Hotel] = Field(default_factory=list)


class TripPlanResponse(StrictModel):
    success: bool
    message: str = ""
    data: TripPlan | None = None

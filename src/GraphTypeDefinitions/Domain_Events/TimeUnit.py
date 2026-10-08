import enum
import strawberry

@strawberry.enum(description="")
class TimeUnit(enum.Enum):
    SECONDS = "seconds"
    MINUTES = "minutes"
    HOURS = "hours"
    DAYS = "days"
    WEEKS = "weeks"
"""NSE trading holidays (equity & F&O segments), weekday holidays only.

Source of truth is the NSE trading-holiday circular published each December:
https://www.nseindia.com/resources/exchange-communication-holidays

MAINTENANCE: append the new year's list every December and verify festival
dates against the circular. The 2026 entries marked provisional below were
compiled before/around the circular's release and MUST be re-verified.
Muhurat-trading days (Diwali Laxmi Pujan) are listed as holidays because the
regular session is closed; the special evening session is out of scope.
"""

from datetime import date

NSE_HOLIDAYS: dict[int, frozenset[date]] = {
    2024: frozenset(
        {
            date(2024, 1, 22),  # Special holiday (Ram Mandir)
            date(2024, 1, 26),  # Republic Day
            date(2024, 3, 8),  # Mahashivratri
            date(2024, 3, 25),  # Holi
            date(2024, 3, 29),  # Good Friday
            date(2024, 4, 11),  # Id-Ul-Fitr
            date(2024, 4, 17),  # Ram Navami
            date(2024, 5, 1),  # Maharashtra Day
            date(2024, 5, 20),  # Lok Sabha election (Mumbai)
            date(2024, 6, 17),  # Bakri Id
            date(2024, 7, 17),  # Muharram
            date(2024, 8, 15),  # Independence Day
            date(2024, 10, 2),  # Mahatma Gandhi Jayanti
            date(2024, 11, 1),  # Diwali Laxmi Pujan (muhurat only)
            date(2024, 11, 15),  # Gurunanak Jayanti
            date(2024, 12, 25),  # Christmas
        }
    ),
    2025: frozenset(
        {
            date(2025, 2, 26),  # Mahashivratri
            date(2025, 3, 14),  # Holi
            date(2025, 3, 31),  # Id-Ul-Fitr
            date(2025, 4, 10),  # Shri Mahavir Jayanti
            date(2025, 4, 14),  # Dr. Ambedkar Jayanti
            date(2025, 4, 18),  # Good Friday
            date(2025, 5, 1),  # Maharashtra Day
            date(2025, 8, 15),  # Independence Day
            date(2025, 8, 27),  # Ganesh Chaturthi
            date(2025, 10, 2),  # Gandhi Jayanti / Dussehra
            date(2025, 10, 21),  # Diwali Laxmi Pujan (muhurat only)
            date(2025, 10, 22),  # Balipratipada
            date(2025, 11, 5),  # Gurunanak Jayanti
            date(2025, 12, 25),  # Christmas
        }
    ),
    # PROVISIONAL — verify against the official NSE circular for 2026.
    2026: frozenset(
        {
            date(2026, 1, 26),  # Republic Day
            date(2026, 3, 4),  # Holi (provisional)
            date(2026, 3, 20),  # Id-Ul-Fitr (provisional)
            date(2026, 3, 26),  # Ram Navami (provisional)
            date(2026, 3, 31),  # Shri Mahavir Jayanti (provisional)
            date(2026, 4, 3),  # Good Friday
            date(2026, 4, 14),  # Dr. Ambedkar Jayanti
            date(2026, 5, 1),  # Maharashtra Day
            date(2026, 5, 27),  # Bakri Id (provisional)
            date(2026, 6, 26),  # Muharram (provisional)
            date(2026, 10, 2),  # Mahatma Gandhi Jayanti
            date(2026, 10, 20),  # Dussehra (provisional)
            date(2026, 11, 10),  # Balipratipada (provisional)
            date(2026, 11, 24),  # Gurunanak Jayanti (provisional)
            date(2026, 12, 25),  # Christmas
        }
    ),
}

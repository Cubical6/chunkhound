"""HTTP payment boundary."""

import requests


class PaymentGateway:
    def charge(self, total: int) -> None:
        requests.post("https://payments.example.invalid/charge", json={"total": total})


def load_gateway() -> PaymentGateway:
    return PaymentGateway()

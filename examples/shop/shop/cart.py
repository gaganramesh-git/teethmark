"""A tiny shopping cart, used to demonstrate teethmark."""


def line_total(price, qty):
    """Price for one line. Ten or more of the same item get 10% off."""
    total = price * qty
    if qty >= 10:
        total = total * 0.9
    return round(total, 2)


def cart_total(lines, coupon=None):
    """Total for a list of (price, qty) lines. WELCOME5 takes 5 off carts over 20."""
    total = sum(line_total(price, qty) for price, qty in lines)
    if coupon == "WELCOME5" and total > 20:
        total -= 5
    return round(total, 2)


def shipping(total, express=False):
    """Standard shipping is free from 50 up. Express always costs 9.5."""
    if total >= 50 and not express:
        return 0.0
    return 9.5 if express else 4.0

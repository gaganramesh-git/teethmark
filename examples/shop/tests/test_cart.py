from shop.cart import cart_total, line_total, shipping


def test_line_total_plain():
    assert line_total(2.5, 4) == 10.0


def test_bulk_discount_starts_at_ten():
    assert line_total(1.0, 9) == 9.0
    assert line_total(1.0, 10) == 9.0
    assert line_total(2.0, 10) == 18.0


def test_cart_total_adds_lines():
    assert cart_total([(2.5, 4), (1.0, 3)]) == 13.0


def test_coupon_needs_more_than_twenty():
    assert cart_total([(10.0, 2)], coupon="WELCOME5") == 20.0
    assert cart_total([(10.5, 2)], coupon="WELCOME5") == 16.0
    assert cart_total([(10.5, 2)], coupon="NOPE") == 21.0


def test_shipping_rules():
    assert shipping(49.99) == 4.0
    assert shipping(50) == 0.0
    assert shipping(80, express=True) == 9.5
    assert shipping(10, express=True) == 9.5

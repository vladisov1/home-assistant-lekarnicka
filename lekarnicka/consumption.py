"""Validated inventory changes for an individual physical package.

A package's initial capacity is immutable after tracking starts. The balance is
always read from the database, never from a submitted form field.
"""

ALLOWED_UNITS = frozenset(('tablety', 'kapsle', 'sáčky', 'čípky', 'kusy'))


def apply_consumption(initial, remaining, unit, raw_initial, raw_consumed, selected_unit):
    """Return (initial, remaining, unit), or raise ValueError.

    Blank initial values mean tracking has not started. Existing tracked units
    cannot be silently changed. No new consumption can be posted without a
    valid initial capacity and an explicit supported unit.
    """
    raw_initial = str(raw_initial or '').strip()
    raw_consumed = str(raw_consumed if raw_consumed is not None else '0').strip()
    if not raw_consumed or not raw_consumed.isascii() or not raw_consumed.isdecimal():
        raise ValueError('Neplatný odečet.')
    consumed = int(raw_consumed)
    if initial is None:
        if not raw_initial:
            if consumed:
                raise ValueError('Nejprve zadejte počáteční množství.')
            return None, None, unit
        if not raw_initial.isascii() or not raw_initial.isdecimal():
            raise ValueError('Neplatná počáteční kapacita.')
        initial = int(raw_initial)
        if not 1 <= initial <= 100000:
            raise ValueError('Neplatná počáteční kapacita.')
        remaining = initial
        if selected_unit not in ALLOWED_UNITS:
            raise ValueError('Neplatná jednotka.')
        unit = selected_unit
    else:
        if not isinstance(initial, int) or not isinstance(remaining, int):
            raise ValueError('Neúplná evidence spotřeby.')
        if raw_initial and (not raw_initial.isascii() or not raw_initial.isdecimal() or int(raw_initial) != initial):
            raise ValueError('Počáteční kapacitu nelze změnit.')
        if unit not in ALLOWED_UNITS or selected_unit != unit:
            raise ValueError('Jednotku sledovaného balení nelze změnit.')
    if not 0 <= consumed <= remaining <= initial:
        raise ValueError('Odečet překračuje zbývající zásobu.')
    return initial, remaining - consumed, unit

// Pure restocking recommendation logic (no Vue imports).

const growthOf = (forecast) => {
  const current = Number(forecast.current_demand)
  const forecasted = Number(forecast.forecasted_demand)
  // Guard against divide-by-zero: an item with no current demand but some forecast ranks first
  if (!(current > 0)) return forecasted > 0 ? Infinity : 0
  return (forecasted - current) / current
}

export function recommendRestock(forecasts, budget) {
  const ranked = (forecasts || [])
    .filter(f => typeof f.unit_cost === 'number' && f.unit_cost > 0)
    .map(f => ({ forecast: f, growth: growthOf(f) }))
    .sort((a, b) => b.growth - a.growth)

  const items = []
  let remaining = Math.max(Number(budget) || 0, 0)
  let totalSpend = 0

  for (const { forecast } of ranked) {
    // Order the forecasted demand as-is. Stock on hand is deliberately not netted
    // out because forecast SKUs do not overlap with the inventory data.
    const quantity = Math.round(Number(forecast.forecasted_demand))
    if (!(quantity > 0)) continue

    // Round to cents so float noise (e.g. 9.4 * 950) can't break the budget check
    const lineTotal = Math.round(forecast.unit_cost * quantity * 100) / 100
    // Skip-and-continue: an item that does not fit must not block cheaper,
    // lower-ranked items that still fit in the remaining budget.
    if (lineTotal > remaining) continue

    items.push({
      sku: forecast.item_sku,
      name: forecast.item_name,
      trend: forecast.trend,
      quantity,
      unit_cost: forecast.unit_cost,
      line_total: lineTotal,
      lead_time_days: forecast.lead_time_days
    })
    remaining = Math.round((remaining - lineTotal) * 100) / 100
    totalSpend = Math.round((totalSpend + lineTotal) * 100) / 100
  }

  const leadTimeDays = items.reduce((max, item) => Math.max(max, item.lead_time_days || 0), 0)

  return { items, totalSpend, remaining, leadTimeDays }
}

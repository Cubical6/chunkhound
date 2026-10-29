/** Order identifier returned by the shop API. */
export interface Order {
  id: string;
}

/** Fetches the storefront's orders from the shop API. */
export async function fetchOrders(): Promise<Order[]> {
  const response = await fetch('/api/orders');
  return response.json();
}

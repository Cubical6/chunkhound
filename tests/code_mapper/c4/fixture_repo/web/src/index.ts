import {fetchOrders} from './api';
import type {Order} from './api';

/** Loads the orders displayed by the web storefront. */
export async function main(): Promise<Order[]> {
  return fetchOrders();
}

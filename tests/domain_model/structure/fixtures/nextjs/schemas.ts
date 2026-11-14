import { z } from 'zod';
export const TeamInput = z.object({
  name: z.string().min(1),
  email: z.string().email(),
}).strict();
export const UnusedInput = z.object({ secret: z.string() });

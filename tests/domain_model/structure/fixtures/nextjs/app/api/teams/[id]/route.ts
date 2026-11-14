import { TeamInput } from '../../../../schemas';
export async function GET() {
  return [];
}
const create = async (request) => {
  const input = TeamInput.safeParse(await request.json());
  TeamInput.parse(input);
  return input;
};
export { create as POST };

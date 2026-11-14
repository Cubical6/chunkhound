// Server-only entry points.
'use server';
export async function addTeam(input) {
  return input;
}
export const removeTeam = async (id) => {
  return id;
};
export const version = () => 1;

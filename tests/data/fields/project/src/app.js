import OpenAI from "openai";

const client = new OpenAI();
const model = "gpt-4o-mini";
export async function ask(q) {
  return client.chat.completions.create({ model, messages: [{ role: "user", content: q }] });
}

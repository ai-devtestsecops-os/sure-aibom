// 색 모드 메뉴 열고 닫기. 모드 적용과 저장은 Material 의 palette JS 가 radio 입력으로 처리한다.
// 페이지를 다시 열면 Material 은 저장된 색만 body 에 적용하고 radio 는 건드리지 않으므로, 저장된 index 의 radio 를 여기서 checked 로
// 맞춰 둔다 (현재 모드 아이콘과 메뉴의 굵은 글씨가 radio 의 :checked 를 본다).
document.addEventListener("DOMContentLoaded", () => {
  const menu = document.querySelector(".palette-menu");
  if (!menu) return;
  const inputs = Array.from(menu.querySelectorAll("input[name='__palette']"));
  let index = -1;
  try {                                                   // Material 과 같은 키(__md_get)로 저장값을 읽는다
    const saved = typeof __md_get === "function" ? __md_get("__palette") : null;
    if (saved && Number.isInteger(saved.index)) index = saved.index;
  } catch (e) { /* 저장값이 없거나 깨짐 */ }
  if (index < 0)                                          // 저장값이 없으면 Material 처럼 media 가 맞는 첫 항목 (System)
    index = inputs.findIndex((i) => window.matchMedia(i.getAttribute("data-md-color-media")).matches);
  if (inputs[Math.max(0, index)]) inputs[Math.max(0, index)].checked = true;
  const button = menu.querySelector(".palette-menu__button");
  const setOpen = (open) => { menu.classList.toggle("palette-menu--open", open); button.setAttribute("aria-expanded", String(open)); };
  button.addEventListener("click", (e) => { e.stopPropagation(); setOpen(!menu.classList.contains("palette-menu--open")); });
  menu.querySelectorAll(".palette-menu__item").forEach((item) => item.addEventListener("click", () => setOpen(false)));
  document.addEventListener("click", (e) => { if (!menu.contains(e.target)) setOpen(false); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") setOpen(false); });
});

/* Decorative background, independent of the application's forms and chat. */
document.addEventListener('DOMContentLoaded', () => {
  const scene = document.createElement('div');
  scene.className = 'ambient-scene';
  scene.setAttribute('aria-hidden', 'true');
  for (let index = 0; index < 3; index++) {
    const light = document.createElement('span');
    light.className = `ambient-light ambient-light-${index + 1}`;
    scene.append(light);
  }
  document.body.prepend(scene);
});

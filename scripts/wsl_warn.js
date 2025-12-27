#!/usr/bin/env node
const cwd = process.cwd();
const isWSL = !!process.env.WSL_DISTRO_NAME;
if (isWSL && cwd.startsWith('/mnt/')) {
  const srcDefault = '/mnt/c/Users/justi/OneDrive/Desktop/MyProjects/dullyPDF';
  const destDefault = `${process.env.HOME || '~'}/projects/dullyPDF`;
  console.log('[wsl-note] Detected WSL in a Windows-mounted path:', cwd);
  console.log('[wsl-note] File watching and installs are slower on /mnt/* and OneDrive.');
  console.log('[wsl-note] For a faster dev loop, migrate to WSL ext4:');
  console.log(`          npm run migrate:wsl`);
  console.log(`          (defaults src: ${srcDefault}, dest: ${destDefault})`);
}
process.exit(0);

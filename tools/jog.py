import sys, time, serial, os
# ponytail: Uno resets on every serial open, so Z position is tracked here in a file.
# Z bottom hard stop = 0 (+Z is down). Upgrade path: firmware soft limits once the setup stays connected.
ZF = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'zpos.txt')
z = float(open(ZF).read()) if os.path.exists(ZF) else 0.0
if sys.argv[1:2] and sys.argv[1].startswith('@'):
    sys.argv[1:] = open(sys.argv[1][1:]).read().split('\n')
    sys.argv = [a for a in sys.argv if a.strip()]
for c in sys.argv[1:]:
    for w in c.split()[1:]:
        if c.startswith('J') and w[0] == 'Z':
            z += float(w[1:])
            if z > 0.001:
                sys.exit(f'refused: {c} goes {z:.2f} mm past the bottom stop')
s = serial.Serial('COM6', 115200, timeout=60); time.sleep(2.5); s.reset_input_buffer()
def cmd(c):
    s.write((c + '\n').encode()); r = s.readline().decode().strip(); print(c, '->', r); return r
for c in ['$XMM='+os.environ.get('XMM','5'), '$YMM='+os.environ.get('YMM','5'), '$ZMM='+os.environ.get('ZMM','160'), 'M17'] + sys.argv[1:]:
    cmd(c)
cmd('M18')
open(ZF, 'w').write(str(z)); print('Z from bottom:', z)

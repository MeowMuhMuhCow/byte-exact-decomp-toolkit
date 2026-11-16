// OPT -4r -oneatx -zp1 -s

//@ f_400000
int f_400000(int x, int lo, int hi)
{
    if (x < lo) return lo;
    if (x > hi) return hi;
    return x;
}

//@ f_400020
int f_400020(short *arr, int count, int scale)
{
    int total = 0;
    int i;
    for (i = 0; i < count; i++) {
        total = total - (int)arr[i] * scale;
    }
    return total;
}

//@ f_400050
int f_400050(int op, int a, int b)
{
    switch (op) {
    case 0:
        return a + b;
    case 1:
        return a - b;
    case 2:
        return a * b;
    case 3:
        return (b != 0) ? (a / b) : 0;
    case 4:
        return (a ^ b) & 0xff;
    default:
        return -1;
    }
}

//@ f_4000b0
int f_4000b0(short *buf, int n, int mode)
{
    int s = f_400020(buf, n, 3);
    int d = f_400050(mode, s, 10);
    return f_400000(d, 0, 1000);
}

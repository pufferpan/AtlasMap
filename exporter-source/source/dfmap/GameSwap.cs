using CUE4Parse.FileProvider;
using CUE4Parse.UE4.Versions;

namespace Dfmap;

/// <summary>
/// Game stores each static-mesh LOD as an FByteBulkData blob inside the package's
/// .ubulk (the Tencent "streamed static mesh" layout). CUE4Parse only implements that
/// layout under its Tencent profiles, so mesh packages are read with a temporary game-id
/// swap while everything else keeps the Game profile - the mount itself must stay
/// on GAME_DeltaForce because that profile carries the custom pak AES handling.
/// </summary>
public sealed class GameSwapScope : IDisposable
{
    private readonly IFileProvider _provider;
    private EGame _saved;
    private readonly bool _active;

    public GameSwapScope(IFileProvider provider, string game)
    {
        _provider = provider;
        if (string.IsNullOrEmpty(game) || !Enum.TryParse<EGame>(game, true, out var g)) return;
        try
        {
            _saved = provider.Versions.Game;
            provider.Versions.Game = g;
            _active = true;
        }
        catch
        {
            _active = false;
        }
    }

    public void Dispose()
    {
        if (_active) _provider.Versions.Game = _saved;
    }
}
